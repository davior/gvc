"""Rendering a project, following the render, and fetching what it made."""

import json
import mimetypes
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlmodel import Session, select

from app.auth import CallerToken, CurrentUser, sign_media_key, verify_media_signature
from app.database import get_session
from app.jobs.runner import ACTIVE_STATUSES
from app.media.ranged import ranged_response
from app.models.render import RenderJob
from app.render import worker
from app.render.estimate import estimate
from app.schemas import DataResponse, ListResponse
from app.schemas_renders import EstimateRead, RenderCreate, RenderRead
from app.services import projects as project_service

router = APIRouter()
media_router = APIRouter()

_FILES = ("video.mp4", "subtitles.srt", "poster.jpg")


def _signed(job: RenderJob, name: Optional[str]) -> Optional[str]:
    if not name or job.status != "done":
        return None
    key = f"{job.id}/{name}"
    expires_at, signature = sign_media_key(key)
    return f"/media/renders/{key}?exp={expires_at}&sig={signature}"


def _read(job: RenderJob) -> RenderRead:
    return RenderRead(
        id=job.id, project_id=job.project_id, version=job.version_seq, preview=job.preview,
        status=job.status, stage=job.stage, progress=job.progress, detail=job.detail,
        error=job.error_message, warnings=json.loads(job.warnings or "[]"),
        duration=job.duration, size_bytes=job.size_bytes, narration_chars=job.narration_chars,
        video_url=_signed(job, job.video_path), subtitles_url=_signed(job, job.subtitle_path),
        poster_url=_signed(job, job.poster_path),
        created_at=job.created_at, updated_at=job.updated_at,
    )


def _owned(session: Session, user, render_id: str) -> RenderJob:
    job = session.get(RenderJob, render_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": "Render not found"})
    return job


@router.post("/projects/{project_id}/estimate", response_model=DataResponse[EstimateRead])
def estimate_project(project_id: str, user: CurrentUser,
                     session: Session = Depends(get_session)) -> DataResponse[EstimateRead]:
    """How long the saved version would run, and what would stop it rendering."""
    project = project_service.get_owned(session, user, project_id)
    spec = project_service.require_spec(project_service.decode(project.spec))
    result = estimate(spec)
    return DataResponse(data=EstimateRead(**result.__dict__))


@router.post("/projects/{project_id}/renders", response_model=DataResponse[RenderRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_render(project_id: str, body: RenderCreate, user: CurrentUser, token: CallerToken,
                 session: Session = Depends(get_session)) -> DataResponse[RenderRead]:
    """Render the project as it is saved now. Later edits never change this render."""
    project = project_service.get_owned(session, user, project_id)
    spec = project_service.require_spec(project_service.decode(project.spec))
    checked = estimate(spec)
    blocks = checked.blocks_preview if body.preview else checked.blocks_render
    if blocks:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "not_renderable", "message": " ".join(blocks)})
    running = session.exec(select(RenderJob).where(
        RenderJob.project_id == project.id, RenderJob.status.in_(ACTIVE_STATUSES))).first()
    if running is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "render_running",
                                    "message": "This project is already rendering"})
    job = worker.submit(session, project, user_id=user.id, token=token, preview=body.preview)
    return DataResponse(data=_read(job))


@router.get("/projects/{project_id}/renders", response_model=ListResponse[RenderRead])
def list_renders(project_id: str, user: CurrentUser, limit: int = Query(default=20, ge=1, le=100),
                 session: Session = Depends(get_session)) -> ListResponse[RenderRead]:
    project = project_service.get_owned(session, user, project_id)
    rows = session.exec(select(RenderJob).where(RenderJob.project_id == project.id)
                        .order_by(RenderJob.created_at.desc()).limit(limit)).all()
    return ListResponse(data=[_read(r) for r in rows], total=len(rows), limit=limit, offset=0)


@router.get("/renders/{render_id}", response_model=DataResponse[RenderRead])
def get_render(render_id: str, user: CurrentUser,
               session: Session = Depends(get_session)) -> DataResponse[RenderRead]:
    return DataResponse(data=_read(_owned(session, user, render_id)))


@router.post("/renders/{render_id}/cancel", response_model=DataResponse[RenderRead])
def cancel_render(render_id: str, user: CurrentUser,
                  session: Session = Depends(get_session)) -> DataResponse[RenderRead]:
    job = _owned(session, user, render_id)
    if job.status in ACTIVE_STATUSES:
        worker.queue.cancel(job.id)
        if job.status == "queued":
            # Never picked up, so nothing will unwind it: say so now.
            job.status, job.stage = "cancelled", ""
            session.add(job)
            session.commit()
            session.refresh(job)
    return DataResponse(data=_read(job))


@router.delete("/renders/{render_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_render(render_id: str, user: CurrentUser,
                  session: Session = Depends(get_session)) -> Response:
    job = _owned(session, user, render_id)
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "render_running", "message": "Cancel it first"})
    shutil.rmtree(worker.renders_dir() / job.id, ignore_errors=True)
    session.delete(job)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@media_router.get("/{render_id}/{name}")
def serve_render_file(
    render_id: str, name: str,
    exp: int = Query(...), sig: str = Query(...),
    range_header: Optional[str] = Header(default=None, alias="Range"),
):
    """A finished render's file, by signed URL; ranged, so a long video can scrub."""
    if name not in _FILES or not verify_media_signature(f"{render_id}/{name}", exp, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail={"code": "invalid_signature",
                                    "message": "This link is invalid or has expired"})
    path = worker.renders_dir() / render_id / name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": "No such file"})
    return ranged_response(open(path, "rb"), size=path.stat().st_size,
                           media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                           range_header=range_header, cache_seconds=3600)
