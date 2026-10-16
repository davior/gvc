"""Projects: list, create (blank, pasted or pushed from Notes), edit, history."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session, func, select

from app.auth import CurrentUser
from app.database import get_session
from app.models.project import Project, ProjectVersion
from app.schemas import DataResponse, ListResponse
from app.schemas_projects import (
    ProjectCreate, ProjectImport, ProjectRead, ProjectSummary, SpecSave, VersionDetail,
    VersionRead,
)
from app.services import projects as service
from app.spec.starter import starter_spec

router = APIRouter()


def _summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        id=project.id, title=project.title, origin=project.origin, version=project.head_seq,
        created_at=project.created_at, updated_at=project.updated_at,
    )


def _read(project: Project) -> ProjectRead:
    spec = service.decode(project.spec)
    return ProjectRead(
        **_summary(project).model_dump(), spec=spec,
        pending_note_media=service.pending_note_media(spec),
    )


def _version(version: ProjectVersion) -> VersionRead:
    return VersionRead(
        id=version.id, seq=version.seq, author=version.author, message=version.message,
        reverted_from=version.reverted_from, created_at=version.created_at,
    )


@router.get("", response_model=ListResponse[ProjectSummary])
def list_projects(
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ListResponse[ProjectSummary]:
    where = Project.user_id == user.id
    total = session.exec(select(func.count()).select_from(Project).where(where)).one()
    rows = session.exec(
        select(Project).where(where).order_by(Project.updated_at.desc()).offset(offset).limit(limit)
    ).all()
    return ListResponse(data=[_summary(p) for p in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=DataResponse[ProjectRead], status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[ProjectRead]:
    """A blank project to build by hand, or one started from a pasted spec."""
    if body.spec is None:
        spec = starter_spec(body.title)
        origin, message = "blank", "Created"
    else:
        spec = service.require_spec(body.spec)
        # A pasted spec may carry its own provenance (a note, a brief), and keeps it.
        origin, message = "pasted", "Created from a pasted spec"
        if body.title.strip():
            spec.title = body.title.strip()
    project = service.create(session, user, spec, origin=origin, message=message)
    return DataResponse(data=_read(project))


@router.post("/import", response_model=DataResponse[ProjectRead], status_code=status.HTTP_201_CREATED)
def import_project(
    body: ProjectImport, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[ProjectRead]:
    """Where Notes' "Make video" pushes a note.

    A one-way hand-off: the project is GVC's from here on, and nothing reads the note
    again. Accepts whatever spec_version Notes emits (0.1 today) and migrates it.
    """
    spec = service.stamp_note_source(service.require_spec(body.spec))
    project = service.create(session, user, spec, origin="note", message="Pushed from Gecko Notes")
    return DataResponse(data=_read(project))


@router.get("/{project_id}", response_model=DataResponse[ProjectRead])
def get_project(
    project_id: str, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[ProjectRead]:
    return DataResponse(data=_read(service.get_owned(session, user, project_id)))


@router.put("/{project_id}", response_model=DataResponse[ProjectRead])
def save_project(
    project_id: str, body: SpecSave, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[ProjectRead]:
    """Replace the spec with an edited one, as a new version.

    The whole spec, not a patch: in M0 every edit comes from the editor, which holds the
    whole document anyway. Operations addressed by id arrive with AI editing (M5).
    """
    project = service.get_owned(session, user, project_id)
    spec = service.require_spec(body.spec)
    service.save(session, project, spec, message=body.message)
    return DataResponse(data=_read(project))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str, user: CurrentUser, session: Session = Depends(get_session)
) -> Response:
    service.delete(session, service.get_owned(session, user, project_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/versions", response_model=ListResponse[VersionRead])
def list_versions(
    project_id: str,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ListResponse[VersionRead]:
    project = service.get_owned(session, user, project_id)
    rows, total = service.versions(session, project, limit=limit, offset=offset)
    return ListResponse(data=[_version(v) for v in rows], total=total, limit=limit, offset=offset)


@router.get("/{project_id}/versions/{version_id}", response_model=DataResponse[VersionDetail])
def get_version(
    project_id: str, version_id: str, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[VersionDetail]:
    project = service.get_owned(session, user, project_id)
    version = service.get_version(session, project, version_id)
    return DataResponse(data=VersionDetail(**_version(version).model_dump(),
                                           spec=service.decode(version.spec)))


@router.post("/{project_id}/revert/{version_id}", response_model=DataResponse[ProjectRead])
def revert_project(
    project_id: str, version_id: str, user: CurrentUser, session: Session = Depends(get_session)
) -> DataResponse[ProjectRead]:
    project = service.get_owned(session, user, project_id)
    service.revert(session, project, service.get_version(session, project, version_id))
    return DataResponse(data=_read(project))
