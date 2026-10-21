"""Request and response bodies for the assistant."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TurnCreate(BaseModel):
    # None: continue in a new session (for this project, or for a new video).
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    prompt: str = Field(min_length=1, max_length=20_000)
    # The editor's draft, unsaved edits included. Absent: the saved version (or, with
    # no project, a blank starter).
    draft_spec: Optional[Dict[str, Any]] = None
    # The project version the draft was opened from.
    base_version: Optional[int] = None
    # The segment open in the editor, if any.
    focus: Optional[str] = None


class Step(BaseModel):
    kind: str
    text: str


class TurnRead(BaseModel):
    id: str
    session_id: str
    project_id: Optional[str] = None
    status: str
    stage: str
    detail: str
    error: Optional[str] = None
    prompt: str
    steps: List[Step] = []
    reply: str = ""
    # Present while there is a proposal: the whole spec to load into the editor.
    proposed_spec: Optional[Dict[str, Any]] = None
    changes: List[str] = []
    outcome: str = ""
    base_version: Optional[int] = None
    cost: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    role: str
    text: str
    turn_id: Optional[str] = None
    at: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    created_at: datetime
    updated_at: datetime


class AttachmentRead(BaseModel):
    """An attachment as listed: what it is and how much of it, not its whole text."""

    id: str
    kind: str
    title: str
    source: str
    chars: int
    truncated: bool = False
    # The start of the text, so a person can see what was read.
    preview: str = ""
    added_at: Optional[str] = None


class SessionCreate(BaseModel):
    # None: a conversation about a video not yet made (from the project list).
    project_id: Optional[str] = None


class NoteAttach(BaseModel):
    note_id: str = Field(min_length=1, max_length=200)


class UrlAttach(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class NoteChoice(BaseModel):
    id: str
    title: str
    preview: str = ""
    modified_at: Optional[str] = None


class SessionRead(SessionSummary):
    messages: List[Message] = []
    attachments: List[AttachmentRead] = []
    # Every turn of the session, newest last, so the panel can show each one's steps,
    # change card and cost beside its message.
    turns: List[TurnRead] = []
    cost: float = 0.0


class NewProjectRead(BaseModel):
    project_id: str
