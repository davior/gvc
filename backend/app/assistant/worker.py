"""Running assistant turns in the background, as the user who asked.

A turn searches GAM with the requester's own token, so it can never see what they could
not. The token is held here, in memory, for the turn's life only, never in the database,
which is why a server restart ends a running turn ("ask again") rather than resuming it:
the render queue's rule, for the same reason.

Everything else lives on the `AssistantTurn` row as it happens, so a turn finishes and
waits for Apply with nobody watching.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session

from app.assistant import loop
from app.assistant.attachments import material
from app.assistant.prompt import REFERENCE, context
from app.assistant.tools import Working
from app.clock import utcnow
from app.config import settings
from app.gam.client import GamClient
from app.generation import service as generation_service
from app.jobs.runner import JobQueue, readable_error, set_fields
from app.models.assistant import AssistantSession, AssistantTurn
from app.providers import build_provider
from app.providers.base import ProviderError, Reply
from app.spec.model import dump_spec
from app.spec.validation import parse_spec
from app.usage import events as usage_events

logger = logging.getLogger(__name__)

_tokens: Dict[str, Optional[str]] = {}

MAX_STEPS_KEPT = 200


def append_message(row: AssistantSession, role: str, text: str,
                   turn_id: Optional[str] = None) -> None:
    messages = json.loads(row.messages or "[]")
    messages.append({"role": role, "text": text, "turn_id": turn_id,
                     "at": utcnow().isoformat(timespec="seconds")})
    row.messages = json.dumps(messages, ensure_ascii=False)
    row.updated_at = utcnow()


def history_for(row: AssistantSession, turn_id: str) -> List[Tuple[str, str]]:
    """Earlier messages, newest kept, with this turn's own prompt left out (it is sent
    as the new message)."""
    messages = [m for m in json.loads(row.messages or "[]")
                if m.get("turn_id") != turn_id and m.get("text")
                and m.get("role") in ("user", "assistant")]
    return [(m["role"], m["text"]) for m in messages[-settings.assistant_history_messages:]]


def _canonical(data: dict) -> Optional[dict]:
    spec, issues = parse_spec(data)
    return dump_spec(spec) if spec is not None else None


def _run(turn_id: str) -> None:
    with queue.session() as session:
        turn = session.get(AssistantTurn, turn_id)
        if turn is None or turn.status != "queued":
            return
        chat = session.get(AssistantSession, turn.session_id)
        if turn_id not in _tokens:
            set_fields(session, turn, status="error", stage="",
                       error_message="Interrupted by a restart of the server. Ask again.")
            if chat:
                append_message(chat, "assistant", "_Interrupted by a restart. Ask again._", turn_id)
                session.add(chat)
                session.commit()
            return
        set_fields(session, turn, status="processing", stage="Thinking", progress=0)
        user_id, project_id = turn.user_id, turn.project_id
        prompt, focus = turn.prompt, turn.focus
        base = json.loads(turn.base_spec or "{}")
        history = history_for(chat, turn_id) if chat else []
        attached = material(json.loads(chat.attachments or "[]")) if chat else ""

    token = _tokens.get(turn_id)
    gam = GamClient(token)
    steps: List[dict] = []
    cost: List[float] = []

    def write(**fields) -> None:
        with queue.session() as session:
            row = session.get(AssistantTurn, turn_id)
            if row is not None:
                set_fields(session, row, **fields)

    def on_step(kind: str, text: str) -> None:
        steps.append({"kind": kind, "text": text[:600]})
        detail = {"search": "searching the library", "edit": "editing",
                  "issue": "fixing", "think": "thinking"}.get(kind, "")
        write(steps=json.dumps(steps[-MAX_STEPS_KEPT:], ensure_ascii=False),
              stage="Working", detail=detail)

    def on_reply(reply: Reply) -> None:
        with queue.session() as session:
            spent = usage_events.record_reply(session, user_id=user_id, project_id=project_id,
                                              turn_id=turn_id, reply=reply)
        if spent is not None:
            cost.append(spent)
            write(cost=round(sum(cost), 6))

    try:
        with queue.session() as session:
            provider = build_provider(session, user_id)
        if provider is None:
            raise ProviderError("No AI provider is set up. Add one in Settings first.")
        working = Working(base, gam=gam, max_generations=settings.assistant_max_generations)

        def generate(data, key, image_prompt, base_ids, outputs):
            with queue.session() as session:
                row = generation_service.start(
                    session, gam, user_id=user_id, project_id=project_id, turn_id=turn_id,
                    spec=data, key=key, prompt=image_prompt, outputs=outputs,
                    base_gam_ids=base_ids)
                # Read inside the session: the commit expired the row, and a detached
                # row can't reload.
                return row.model_label, row.estimate

        working.generate = generate
        system = [REFERENCE, attached,
                  context(base, focus=focus, from_scratch=project_id is None)]
        outcome = loop.run(provider, working, system=system, history=history, prompt=prompt,
                           on_step=on_step, on_reply=on_reply,
                           cancelled=lambda: queue.is_cancelled(turn_id),
                           max_rounds=settings.assistant_max_rounds)
    except loop.Stopped:
        _finish(turn_id, status="cancelled", stage="", message="_Stopped._", steps=steps)
        return
    except ProviderError as exc:
        _finish(turn_id, status="error", stage="", error_message=str(exc),
                message=f"_{exc}_", steps=steps)
        return
    except Exception as exc:  # noqa: BLE001 - a failed turn is a job error, not a crash
        logger.exception("Assistant turn %s failed", turn_id)
        _finish(turn_id, status="error", stage="", error_message=readable_error(exc),
                message="_Something went wrong; ask again._", steps=steps)
        return
    finally:
        gam.close()
        _tokens.pop(turn_id, None)

    reply = outcome.reply or ("Done." if working.changes else "")
    proposed = None
    if working.changes:
        canonical = _canonical(working.data)
        if canonical is None:
            reply += ("\n\nI couldn't get the video into a valid state, so there's nothing to "
                      "apply. Ask me to try again, or say what to change.")
        elif canonical != _canonical(base):
            proposed = canonical
    if outcome.cut_short:
        reply = (reply + "\n\n" if reply else "") + f"_{outcome.cut_short}_"
    _finish(turn_id, status="done", stage="", progress=100, detail="", message=reply,
            steps=steps, reply=reply,
            proposed_spec=json.dumps(proposed, ensure_ascii=False) if proposed else None,
            changes=json.dumps(working.changes if proposed else [], ensure_ascii=False),
            outcome="pending" if proposed else "")


def _finish(turn_id: str, *, message: str, steps: List[dict], **fields) -> None:
    with queue.session() as session:
        turn = session.get(AssistantTurn, turn_id)
        if turn is None:
            return
        set_fields(session, turn, steps=json.dumps(steps[-MAX_STEPS_KEPT:], ensure_ascii=False),
                   **fields)
        chat = session.get(AssistantSession, turn.session_id)
        if chat is not None and message:
            append_message(chat, "assistant", message, turn_id)
            session.add(chat)
            session.commit()


queue = JobQueue(AssistantTurn, _run, name="assistant",
                 concurrency=settings.assistant_concurrency, requeue_on_restart=False)


def submit(session: Session, chat: AssistantSession, *, user_id: str, token: Optional[str],
           prompt: str, base_spec: dict, base_version: Optional[int],
           focus: Optional[str]) -> AssistantTurn:
    turn = AssistantTurn(id=str(uuid.uuid4()), session_id=chat.id, user_id=user_id,
                         project_id=chat.project_id, prompt=prompt,
                         base_spec=json.dumps(base_spec, ensure_ascii=False),
                         base_version=base_version, focus=focus)
    append_message(chat, "user", prompt, turn.id)
    if not chat.title:
        chat.title = prompt.strip().splitlines()[0][:80]
    session.add(turn)
    session.add(chat)
    session.commit()
    session.refresh(turn)
    _tokens[turn.id] = token
    queue.enqueue(turn.id)
    return turn


def start() -> None:
    queue.start()
