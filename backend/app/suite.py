"""Gecko Suite as the assistant's model (`AI_BACKEND=suite`).

Everything this app knows about the suite is here, so the worker and the routes ask
"is the assistant ready" and "give me the model for this turn" without knowing what is
behind it.

Which model a turn uses is the suite's decision, by job: a first draft is `chat.draft`
and an edit to an existing video is `chat.edit`, both falling back to `chat.assistant`,
and the clip-picking pass is `chat.quick`. That is how "a capable model for drafts and a
cheap one for edits" is set up (open decision #4) without any code here.

The suite counts the spend, so none of it is written to this app's own usage table in
this mode. The Usage panel here shows only what was spent before the switch.
"""

from __future__ import annotations

from contextlib import closing
from typing import Optional

import httpx
from fastapi import HTTPException, status
from gecko_suite_client import (
    SuiteChat,
    SuiteClient,
    SuiteError,
    SuiteNotConfigured,
    SuiteUnavailable,
)

from app.config import settings
from app.providers.base import ProviderError

# Tests set this; production leaves it None, which is httpx's real network transport.
TRANSPORT: Optional[httpx.BaseTransport] = None

APP = "gvc"


def enabled() -> bool:
    return settings.ai_backend == "suite"


def client(token: Optional[str]) -> SuiteClient:
    """A connection to the suite as the signed-in user, who is the one paying."""
    if not token:
        # Development without Notes (DEV_AUTH_USER) sends no token, and the suite has no
        # way to know who is asking without one.
        raise ProviderError(
            "Gecko Suite needs your Gecko Notes sign-in, and this session has none. "
            "Sign in through Notes, or set AI_BACKEND=local."
        )
    return SuiteClient(settings.suite_base_url, token=token, transport=TRANSPORT)


def task_for(project_id: Optional[str]) -> str:
    """A from-scratch draft and an edit are different jobs, so an admin can give them
    different models. Both fall back to the assistant's own."""
    return "chat.edit" if project_id else "chat.draft"


def chat(connection: SuiteClient, project_id: Optional[str], *,
         task: Optional[str] = None, persona_id: Optional[str] = None) -> SuiteChat:
    return SuiteChat(
        connection,
        task=task or task_for(project_id),
        app=APP,
        persona_id=persona_id,
        # What the spend was for, so the suite's Usage can answer "what did this video
        # cost" (an opaque string to the suite; it keeps no content).
        subject_ref=f"gvc:project:{project_id}" if project_id else None,
    )


def personas(token: Optional[str]) -> list:
    """The personas this person may ask the assistant as: the suite's, for GVC and for every
    app. Empty for any reason at all (the suite down, none made, no session): a picker with
    nothing in it is not shown, and the assistant works without one."""
    try:
        with closing(client(token)) as connection:
            rows = connection.request("GET", "/api/v1/personas", params={"app": APP})
    except (SuiteError, ProviderError):
        return []
    return rows if isinstance(rows, list) else []


def web_search(connection: SuiteClient, query: str, project_id: Optional[str]) -> list:
    """A web search through the suite, credited to the project the turn is about."""
    from gecko_suite_client import web_search as search

    return search(connection, query, app=APP,
                  subject_ref=f"gvc:project:{project_id}" if project_id else None)


def sentence(exc: SuiteError) -> str:
    """What to say to the person when the suite said no. The suite's own messages are
    written for this ("Choose one in Gecko Suite's AI settings"), except for the one
    case where it is not there at all."""
    if isinstance(exc, SuiteUnavailable):
        return ("Gecko Suite can't be reached right now, so the assistant can't answer. "
                "Everything else in Video Creator still works; try again in a moment.")
    return exc.message


def require_ready(token: Optional[str], project_id: Optional[str]) -> dict:
    """Refuse, as an HTTP error, to start a turn nothing could answer; else the model it
    would use. A suite that is down is a 503, not a failure of this app's own work."""
    try:
        with closing(client(token)) as connection:
            model = chat(connection, project_id).resolve()
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "no_session", "message": str(exc)}) from exc
    except SuiteUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "ai_unavailable", "message": sentence(exc)}) from exc
    except SuiteError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail={"code": exc.code, "message": exc.message}) from exc
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "no_provider",
                    "message": "No AI model is set up for the assistant. Choose one in "
                               "Gecko Suite (Routing)."})
    return model


def best_effort_model(token: Optional[str], project_id: Optional[str]) -> Optional[dict]:
    """The model a turn would use, or None for any reason at all. For labelling a draft
    with where it came from, which must never be the reason applying one fails."""
    try:
        with closing(client(token)) as connection:
            return chat(connection, project_id).resolve()
    except (SuiteError, ProviderError):
        return None


__all__ = ["SuiteError", "SuiteNotConfigured", "SuiteUnavailable", "TRANSPORT", "chat", "client",
           "enabled", "require_ready", "sentence", "task_for"]
