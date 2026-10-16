"""A video project and its history.

The spec is stored whole, as JSON text, on the project row, and again on every version.
Snapshots rather than patches, for now: a spec is tens of kilobytes, undo and revert
become "copy that one back", and nothing has to replay a chain to show version 40.

That changes with AI editing (M5), whose staged suggestions need the change itself, not
just the result. Those are stored as id-addressed operations alongside the snapshot (the
Notes spec doc, open decision 14), not as JSON Patch by list index, which would hit the
wrong segment after a reorder.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.clock import utcnow


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    # Mirrors `spec.title`, so the list view never decodes a spec.
    title: str = ""
    spec: str = "{}"                    # the current VideoSpec, JSON
    spec_version: str = ""
    # How it was started: "blank", "pasted", "note" or "brief". Provenance, for the
    # list view; the spec's own `source` carries the detail.
    origin: str = "blank"
    # The newest version's `seq`, so the next one can be numbered without a MAX().
    head_seq: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectVersion(SQLModel, table=True):
    __tablename__ = "project_version"
    # Two writes racing to the same next number must not both succeed: one of them
    # would silently share a slot in the history.
    __table_args__ = (UniqueConstraint("project_id", "seq"),)

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    seq: int                            # 1, 2, 3… within the project
    spec: str                           # snapshot of the whole spec after this change
    # "user" or "ai". Every AI change is recorded as such, so the history can be read
    # as who decided what.
    author: str = "user"
    message: str = ""
    # Set when this version is a revert, naming the version it copied.
    reverted_from: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
