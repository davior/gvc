"""One turn: the model and the tools, round after round, until the model is done.

Pure of the database and the job queue (`worker.py` owns those), so a whole turn can be
run in a test against a scripted provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from app.assistant import tools as T
from app.assistant.tools import Working, _issues_text
from app.providers.base import ChatProvider, Image, Reply

logger = logging.getLogger(__name__)

# Times the loop tells a model that stopped with the video still invalid to fix it.
# Past that it would only be spending the user's money to repeat itself.
MAX_REPAIR_NUDGES = 2

Step = Callable[[str, str], None]


class Stopped(Exception):
    """The user pressed Stop."""


@dataclass
class Outcome:
    reply: str
    # Set when the turn ran out of rounds or output before finishing on its own.
    cut_short: Optional[str] = None
    replies: List[Reply] = field(default_factory=list)


def _first_line(text: str) -> str:
    return text.split("\n", 1)[0].strip()


def run(provider: ChatProvider, working: Working, *, system: Sequence[str],
        history: Sequence[Tuple[str, str]], prompt: str, on_step: Step,
        on_reply: Callable[[Reply], None], cancelled: Callable[[], bool],
        max_rounds: int, images: Sequence[Image] = ()) -> Outcome:
    conversation = provider.conversation(system=system, tools=T.SPECS, history=history,
                                         prompt=prompt, images=images)
    outcome = Outcome(reply="")
    nudges = 0
    for _ in range(max_rounds):
        if cancelled():
            raise Stopped()
        reply = conversation.ask()
        outcome.replies.append(reply)
        on_reply(reply)
        if reply.text:
            outcome.reply = reply.text
        if not reply.tool_calls:
            if reply.stop == "max_tokens":
                outcome.cut_short = ("The reply hit the provider's output limit. Raise the "
                                     "maximum response length in Settings, or ask for less "
                                     "at once.")
                return outcome
            if working.issues and working.changes and nudges < MAX_REPAIR_NUDGES:
                nudges += 1
                on_step("issue", f"{len(working.issues)} issue(s) left to fix")
                conversation.tell("The video still has issues, so it can't be proposed yet. "
                                  "Fix these, then finish:\n" + _issues_text(working.issues))
                continue
            return outcome
        if reply.text:
            on_step("think", reply.text)
        results = []
        for call in reply.tool_calls:
            if cancelled():
                raise Stopped()
            if call.name == "search_assets":
                on_step("search", f"Searching the library: {call.arguments.get('query', '')!r}")
            elif call.name == "read_transcript":
                gam_id = call.arguments.get("gam_id", "")
                seen = working.hits.get(gam_id)
                on_step("search", f"Reading the transcript of {seen.name if seen else gam_id}")
            result = T.execute(working, call)
            results.append(result)
            if call.name in T.READS:
                continue
            on_step("issue" if result.is_error else "edit", _first_line(result.content))
        conversation.answer(results)
    outcome.cut_short = (f"Stopped after {max_rounds} rounds without finishing. What it had "
                         "done so far is below; ask again to carry on.")
    return outcome
