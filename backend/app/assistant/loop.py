"""One turn: the model and the tools, round after round, until the model is done.

The loop itself, meaning when to stop, what a cut-off reply or a refusal means, and that
every tool call is answered exactly once, is `gecko_suite_client.run_agent`, shared with
the other apps' assistants. What is left here is what is this app's: its tools, the
wording of its progress steps, the clip-picking jobs a round runs side by side, and the
rule that a video still failing validation is not finished.

Pure of the database and the job queue (`worker.py` owns those), so a whole turn can be
run in a test against a scripted provider.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Tuple

from gecko_suite_client import Outcome, Stopped, run_agent

from app import suite
from app.assistant import tools as T
from app.assistant.tools import Working, _issues_text
from app.providers.base import ChatProvider, Image, Reply, ToolResult

logger = logging.getLogger(__name__)

# Times the loop tells a model that stopped with the video still invalid to fix it.
# Past that it would only be spending the user's money to repeat itself.
MAX_REPAIR_NUDGES = 2

# Where the limit is raised depends on who runs the model: GVC's own provider row, or
# the suite. Pointing a suite user at GVC's Settings sent them to a field the turn never
# read, so the sentence follows AI_BACKEND.
OUTPUT_LIMIT = ("The reply hit the provider's output limit. Raise the maximum response "
                "length in Settings, or ask for less at once.")
SUITE_OUTPUT_LIMIT = ("The reply hit the model's output limit. Raise Max tokens on its "
                      "provider in Gecko Suite (or CHAT_MAX_TOKENS there), or ask for less "
                      "at once.")


def output_limit_message() -> str:
    return SUITE_OUTPUT_LIMIT if suite.enabled() else OUTPUT_LIMIT

Step = Callable[[str, str], None]

# Re-exported: the worker catches `loop.Stopped`, and it must be the class `run_agent`
# raises, not a second one that only looks like it.
__all__ = ["MAX_REPAIR_NUDGES", "Outcome", "Stopped", "output_limit_message", "run"]


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def run(provider: ChatProvider, working: Working, *, system: Sequence[str],
        history: Sequence[Tuple[str, str]], prompt: str, on_step: Step,
        on_reply: Callable[[Reply], None], cancelled: Callable[[], bool],
        max_rounds: int, images: Sequence[Image] = (),
        on_delta: Optional[Callable[[str], None]] = None) -> Outcome:
    """`on_delta` streams each reply, handing text over as it arrives. Only a suite
    conversation takes it (GVC's own providers have `ask()` and nothing else), so the
    worker passes it only with AI_BACKEND=suite."""
    conversation = provider.conversation(system=system, tools=T.specs_for(working), history=history,
                                         prompt=prompt, images=images)
    nudges = 0

    def nudge(_reply) -> Optional[str]:
        """The model stopped. If the video is still invalid, say so and let it fix it.

        Counted here as well as by `run_agent`, because reporting the step is this
        function's side effect and it must not fire for a nudge `run_agent` then declines.
        """
        nonlocal nudges
        if not (working.issues and working.changes) or nudges >= MAX_REPAIR_NUDGES:
            return None
        nudges += 1
        on_step("issue", f"{len(working.issues)} issue(s) left to fix")
        return ("The video still has issues, so it can't be proposed yet. "
                "Fix these, then finish:\n" + _issues_text(working.issues))

    def run_round(calls) -> List[ToolResult]:
        results: List[Optional[ToolResult]] = []
        # find_clips calls wait here as jobs, so all the round's picker calls run at once.
        waiting: List[Tuple[int, str, T.ClipJob]] = []
        for call in calls:
            if cancelled():
                raise Stopped()
            if call.name == "search_assets":
                on_step("search", f"Searching the library: {call.arguments.get('query', '')!r}")
            elif call.name == "web_search":
                on_step("search", f"Searching the web: {call.arguments.get('query', '')!r}")
            elif call.name in ("read_transcript", "find_clips"):
                gam_id = call.arguments.get("gam_id", "")
                seen = working.hits.get(gam_id)
                doing = "Reading the transcript of" if call.name == "read_transcript" \
                    else "Picking clips from"
                on_step("search", f"{doing} {seen.name if seen else gam_id}")
            planned = T.plan(working, call)
            if isinstance(planned, T.ClipJob):
                waiting.append((len(results), call.id, planned))
                results.append(None)
                continue
            results.append(planned)
            if call.name in T.READS:
                continue
            on_step("issue" if planned.is_error else "edit", _first_line(planned.content))
        if waiting:
            if cancelled():
                raise Stopped()
            answers = T.finish_clip_jobs(working, [job for _, _, job in waiting])
            for (index, call_id, _), (content, is_error) in zip(waiting, answers):
                results[index] = ToolResult(call_id, content, is_error=is_error)
        return results  # type: ignore[return-value]  # every None was filled above

    return run_agent(
        conversation,
        run_round=run_round,
        nudge=nudge,
        max_nudges=MAX_REPAIR_NUDGES,
        max_tokens_message=output_limit_message(),
        cancelled=cancelled,
        on_reply=on_reply,
        on_step=on_step,
        on_delta=on_delta,
        max_rounds=max_rounds,
    )
