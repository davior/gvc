"""The assistant's conversations and turns.

A turn is a job (the render queue's pattern), so it keeps running after the project, the
tab or the browser is closed, and everything it is and does lives on its row: the prompt,
the draft it started from, each step as it happens, the reply and the proposed spec. A
person coming back finds it running, or finished and waiting for Apply or Discard.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.clock import utcnow


class AssistantSession(SQLModel, table=True):
    __tablename__ = "assistant_session"

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    # None: a conversation about a video that doesn't exist yet (from the project list).
    # No foreign key: deleting a project deletes its sessions explicitly, and a draft
    # applied as a new project fills this in afterwards.
    project_id: Optional[str] = Field(default=None, index=True)
    title: str = ""
    # JSON: [{"role": "user"|"assistant", "text", "turn_id", "at"}]
    messages: str = "[]"
    # JSON: [{"id", "kind": "file"|"note"|"url", "title", "source", "text", "chars",
    # "truncated", "added_at"}]: material attached to work from, as text taken when it
    # was attached (assistant/attachments.py).
    attachments: str = "[]"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AssistantTurn(SQLModel, table=True):
    __tablename__ = "assistant_turn"

    id: str = Field(primary_key=True)
    session_id: str = Field(foreign_key="assistant_session.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    project_id: Optional[str] = Field(default=None, index=True)
    # queued | processing | done | error | cancelled (jobs/runner.py)
    status: str = "queued"
    stage: str = ""
    progress: int = 0
    detail: str = ""
    error_message: Optional[str] = None
    prompt: str = ""
    # The editor's draft when the turn was asked, unsaved edits included (JSON), and the
    # project version it was a draft of. The proposal is built on the draft, so applying
    # it later carries those edits too; the version is what "based on an older version"
    # is judged against.
    base_spec: str = "{}"
    base_version: Optional[int] = None
    # The scene open in the editor, if any: "this scene" in a request means it.
    focus: Optional[str] = None
    # JSON: [{"kind": "think"|"search"|"edit"|"issue"|"note", "text"}]
    steps: str = "[]"
    reply: str = ""
    # JSON of the proposed spec; None when the turn changed nothing.
    proposed_spec: Optional[str] = None
    # JSON list of one-line change summaries.
    changes: str = "[]"
    # pending | applied | discarded, once there is a proposal; "" otherwise.
    outcome: str = ""
    cost: Optional[float] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
