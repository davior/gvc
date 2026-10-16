"""A render of one version of a project."""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.clock import utcnow


class RenderJob(SQLModel, table=True):
    __tablename__ = "render_job"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    # The version rendered: later edits never change a render already asked for.
    version_seq: int
    preview: bool = True
    # queued | processing | done | error | cancelled (jobs/runner.py)
    status: str = "queued"
    stage: str = ""
    progress: int = 0
    detail: str = ""
    error_message: Optional[str] = None
    warnings: str = "[]"            # JSON list of sentences
    # Paths relative to the renders directory; set when done.
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    poster_path: Optional[str] = None
    duration: Optional[float] = None
    size_bytes: Optional[int] = None
    narration_chars: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
