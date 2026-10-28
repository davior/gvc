"""Projects: creating them, saving specs, keeping the history.

Every write goes through `_commit_spec`, which is the only place a spec is serialised
into a row. So "the stored spec is valid, current-version and has the project's id"
holds for every project, however it was made.
"""

from __future__ import annotations

import json
import uuid
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, func, select

from app.auth import UserCtx
from app.clock import utcnow
from app.models.project import Project, ProjectVersion
from app.services import themes
from app.services.users import ensure_user
from app.spec.model import NoteSource, VideoSpec, dump_spec
from app.spec.validation import SpecIssue, parse_spec


def invalid_spec(issues: List[SpecIssue]) -> HTTPException:
    """422 carrying the issues, in the suite's error shape plus one extra key."""
    count = len(issues)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "invalid_spec",
            "message": f"The spec has {count} problem{'' if count == 1 else 's'}",
            "issues": [issue.model_dump() for issue in issues],
        },
    )


def require_spec(data: dict) -> VideoSpec:
    spec, issues = parse_spec(data)
    if spec is None:
        raise invalid_spec(issues)
    return spec


def get_owned(session: Session, user: UserCtx, project_id: str) -> Project:
    """The caller's project, or 404 — never 403, which would confirm it exists."""
    project = session.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Project not found"},
        )
    return project


def decode(spec_text: str) -> Dict:
    return json.loads(spec_text)


def pending_note_media(spec_data: Dict) -> int:
    return sum(1 for ref in spec_data.get("assets", {}).values() if ref.get("from") == "notes")


def _commit_spec(
    session: Session,
    project: Project,
    spec: VideoSpec,
    *,
    author: str,
    message: str,
    reverted_from: Optional[str] = None,
) -> ProjectVersion:
    # The project's id is the spec's id: one name for the video wherever it travels
    # (a render filed in GAM points back at it). Owned by the server, so a pasted spec
    # carrying another project's id can't claim to be it.
    spec.id = project.id
    data = dump_spec(spec)
    text = json.dumps(data, ensure_ascii=False)
    now = utcnow()

    project.head_seq += 1
    project.spec = text
    project.spec_version = spec.spec_version
    project.title = spec.title.strip() or "Untitled video"
    project.updated_at = now
    version = ProjectVersion(
        id=str(uuid.uuid4()),
        project_id=project.id,
        seq=project.head_seq,
        spec=text,
        author=author,
        message=message,
        reverted_from=reverted_from,
        created_at=now,
    )
    session.add(project)
    session.add(version)
    session.commit()
    session.refresh(project)
    return version


def create(
    session: Session, user: UserCtx, spec: VideoSpec, *, origin: str, message: str,
    author: str = "user", default_theme: bool = True,
) -> Project:
    """A new project. Every way in starts with the user's default theme unless the spec
    names one of theirs; `default_theme=False` is for the assistant's drafts (see
    `themes.settle`)."""
    # The project row has a foreign key to the shadow user, which `/api/me` normally
    # writes first. A Notes push may well be the first request this user ever makes.
    ensure_user(session, user)
    themes.settle(session, user.id, spec, use_default=default_theme)
    now = utcnow()
    project = Project(id=str(uuid.uuid4()), user_id=user.id, origin=origin,
                      created_at=now, updated_at=now)
    _commit_spec(session, project, spec, author=author, message=message)
    return project


def stamp_note_source(spec: VideoSpec) -> VideoSpec:
    """Mark a pushed spec as having come from a note, and when.

    Notes' importer only writes `source` when it was given a note id, so a push may
    arrive without one; it still came from Notes.
    """
    if not isinstance(spec.source, NoteSource):
        spec.source = NoteSource(kind="note")
    if not spec.source.imported_at:
        spec.source.imported_at = utcnow().isoformat(timespec="seconds") + "Z"
    return spec


def save(session: Session, project: Project, spec: VideoSpec, *, message: str) -> ProjectVersion:
    return _commit_spec(session, project, spec, author="user", message=message or "Edited")


def versions(session: Session, project: Project, *, limit: int, offset: int) -> Tuple[List[ProjectVersion], int]:
    total = session.exec(
        select(func.count()).select_from(ProjectVersion).where(ProjectVersion.project_id == project.id)
    ).one()
    rows = session.exec(
        select(ProjectVersion)
        .where(ProjectVersion.project_id == project.id)
        .order_by(ProjectVersion.seq.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


def get_version(session: Session, project: Project, version_id: str) -> ProjectVersion:
    version = session.get(ProjectVersion, version_id)
    if version is None or version.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Version not found"},
        )
    return version


def revert(session: Session, project: Project, version: ProjectVersion) -> ProjectVersion:
    """Make an old version current again, as a new version.

    Forward, never by deleting what came after: a revert is itself a change someone
    might want to undo. The old snapshot goes back through validation, because it may
    predate a spec_version bump and need migrating.
    """
    spec = require_spec(decode(version.spec))
    return _commit_spec(session, project, spec, author="user",
                        message=f"Reverted to version {version.seq}", reverted_from=version.id)


def delete(session: Session, project: Project) -> None:
    # Versions first, flushed on their own. With no relationship declared between the
    # two tables, the unit of work is free to issue the project's DELETE first, which
    # the foreign key refuses.
    from app.models.render import RenderJob
    from app.render.worker import renders_dir
    import shutil

    for job in session.exec(select(RenderJob).where(RenderJob.project_id == project.id)).all():
        shutil.rmtree(renders_dir() / job.id, ignore_errors=True)
    session.exec(sa_delete(RenderJob).where(RenderJob.project_id == project.id))
    # The assistant's conversations about it go too (their spend stays in UsageEvent).
    # Turns before sessions, for the same foreign-key reason as versions.
    from app.models.assistant import AssistantSession, AssistantTurn
    from app.models.generation import Generation

    # Its generations' rows; the pictures themselves stay in the library (GAM's).
    session.exec(sa_delete(Generation).where(Generation.project_id == project.id))

    session.exec(sa_delete(AssistantTurn).where(AssistantTurn.project_id == project.id))
    session.exec(sa_delete(AssistantSession).where(AssistantSession.project_id == project.id))
    session.exec(sa_delete(ProjectVersion).where(ProjectVersion.project_id == project.id))
    session.delete(project)
    session.commit()
