"""Reading the signed-in user's notes from Gecko Notes, as them.

The same arrangement as `app.gam.client`: the caller's own Notes-issued token is
forwarded, so Notes' ownership checks decide what can be read, and GVC can never see a
note its user couldn't. Only reads. GVC never writes to Notes; once a note is attached,
its text is a copy on the conversation, and editing the note afterwards changes nothing
here (D3's rule for pushed notes, applied to attached ones).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app import outbound
from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = 20


class NotesError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class NoteSummary:
    id: str
    title: str
    preview: str
    modified_at: Optional[str]


@dataclass
class Note:
    id: str
    title: str
    # BlockNote JSON, as Notes stores it.
    content: str


class NotesClient:
    def __init__(self, token: Optional[str]):
        if not token:
            # The dev user has no token, and Notes would refuse the request anyway.
            raise NotesError("notes_unavailable",
                             "Gecko Notes can't be reached without a signed-in session",
                             status_code=409)
        self._http = outbound.client(settings.notes_base_url, timeout=TIMEOUT,
                                     headers={"Authorization": f"Bearer {token}"})

    def __enter__(self) -> "NotesClient":
        return self

    def __exit__(self, *exc) -> None:
        self._http.close()

    def _get(self, path: str, **kwargs) -> Dict[str, Any]:
        try:
            response = self._http.get(path, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Notes unreachable at %s: %s", settings.notes_base_url, exc)
            raise NotesError("notes_unavailable", "Could not reach Gecko Notes") from exc
        if response.status_code == 401:
            raise NotesError("notes_rejected_session",
                             "Gecko Notes did not accept your session. Sign in again.")
        if response.status_code == 404:
            raise NotesError("not_found", "That note doesn't exist, or isn't yours",
                             status_code=404)
        if response.status_code != 200:
            raise NotesError("notes_unavailable",
                             f"Gecko Notes answered {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise NotesError("notes_unavailable", "Gecko Notes sent an unreadable answer") from exc

    def search(self, query: str, limit: int = 20) -> List[NoteSummary]:
        """The user's notes, most recently changed first; with a query, those whose
        title or body contains it (Notes' own `search`, a substring match)."""
        params: Dict[str, Any] = {"limit": limit, "sort": "modified_at", "order": "desc"}
        if query.strip():
            params["search"] = query.strip()
        body = self._get("/api/notes", params=params)
        return [NoteSummary(id=n["id"], title=n.get("title") or "Untitled",
                            preview=(n.get("content_preview") or "")[:200],
                            modified_at=n.get("modified_at"))
                for n in body.get("data") or []]

    def get(self, note_id: str) -> Note:
        # An id goes into the path, so it must be one: anything else could walk the URL.
        if not note_id or "/" in note_id or "?" in note_id or "#" in note_id or ".." in note_id:
            raise NotesError("not_found", "That note doesn't exist, or isn't yours",
                             status_code=404)
        data = self._get(f"/api/notes/{note_id}").get("data") or {}
        return Note(id=data.get("id") or note_id, title=data.get("title") or "Untitled",
                    content=data.get("content") or "")
