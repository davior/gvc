"""Request and response bodies for projects and specs.

A spec travels as plain JSON (`Dict[str, Any]`) in both directions, not as the
`VideoSpec` model. On the way in, so an invalid spec reaches `parse_spec` and comes back
as issues with paths the editor can point at, instead of FastAPI's generic 422. On the
way out, so it is written exactly as `dump_spec` spells it.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.spec.validation import SpecIssue

Origin = Literal["blank", "pasted", "note", "brief"]


class ProjectSummary(BaseModel):
    id: str
    title: str
    origin: str
    version: int
    created_at: datetime
    updated_at: datetime


class ProjectRead(ProjectSummary):
    spec: Dict[str, Any]
    # Files a pushed spec still points at inside the note it came from. Copied into
    # GAM from M1; until then, the editor says so rather than letting it look finished.
    pending_note_media: int = 0


class ProjectCreate(BaseModel):
    # Either a title for a blank project, or a whole spec to start from.
    title: str = Field(default="", max_length=300)
    spec: Optional[Dict[str, Any]] = None


class ProjectImport(BaseModel):
    """What Notes' "Make video" sends: the spec its importer built (any version)."""

    spec: Dict[str, Any]


class SpecSave(BaseModel):
    spec: Dict[str, Any]
    message: str = Field(default="", max_length=500)


class VersionRead(BaseModel):
    id: str
    seq: int
    author: str
    message: str
    reverted_from: Optional[str] = None
    created_at: datetime


class VersionDetail(VersionRead):
    spec: Dict[str, Any]


class Validation(BaseModel):
    valid: bool
    issues: List[SpecIssue] = Field(default_factory=list)
    # The spec as it would be stored: migrated, defaults filled in. Only when valid.
    spec: Optional[Dict[str, Any]] = None


class CopyFailureRead(BaseModel):
    key: str
    message: str


class NoteMediaCopy(BaseModel):
    project: ProjectRead
    # Asset keys now pointing at GAM, and the ones still in the note (retryable).
    copied: List[str]
    failed: List[CopyFailureRead]
