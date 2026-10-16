"""Rendering a project, following the render, and fetching what it made."""

import json
import mimetypes
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlmodel import Session, select

from app.auth import CallerToken, CurrentUser, sign_media_key, verify_media_signature
from app.config import settings
from app.database import get_session
from app.gam.client import GamClient, GamError
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
        poster_url=_signed(job, job.poster_path), description=job.description,
        gam_asset_id=job.gam_asset_id,
        gam_asset_url=(f"{settings.gam_base_url.rstrip('/')}/a/{job.gam_asset_id}"
                       if job.gam_asset_id else None),
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


# Generous: the file is on local disk, but a long full-quality render is gigabytes,
# and GAM probes and thumbnails it before it answers.
SAVE_TIMEOUT_SECONDS = 900


@router.post("/renders/{render_id}/save-to-gam", response_model=DataResponse[RenderRead])
def save_to_gam(render_id: str, user: CurrentUser, token: CallerToken,
                session: Session = Depends(get_session)) -> DataResponse[RenderRead]:
    """File a finished render in the user's GAM library (GAM-3).

    Labelled `gvc_export` with the project and render it came from, named after the
    project, and described with its chapters and credits. Saving twice files it once;
    if it was deleted in GAM since, it is filed again.
    """
    job = _owned(session, user, render_id)
    if job.preview:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"code": "preview_not_saveable",
                                    "message": "A preview is a small working copy. Render the "
                                               "full video to save it to GAM."})
    path = worker.renders_dir() / job.id / (job.video_path or "")
    if job.status != "done" or not job.video_path or not path.is_file():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "render_not_done",
                                    "message": "This render has no finished video to save"})
    project = project_service.get_owned(session, user, job.project_id)

    gam = GamClient(token)
    try:
        if job.gam_asset_id and gam.get_asset(job.gam_asset_id) is not None:
            return DataResponse(data=_read(job))
        title = (project.title or "").strip() or "Untitled video"
        with open(path, "rb") as stream:
            asset = gam.upload(
                f"{title}.mp4", stream, "video/mp4",
                fields={"source": "gvc_export", "origin_project_id": project.id,
                        "origin_reference_id": job.id},
                timeout=SAVE_TIMEOUT_SECONDS,
            )
        changes = {"name": f"{title} (v{job.version_seq})"[:255]}
        if job.description:
            changes["description"] = job.description[:20_000]
        # Best effort: the file is safely filed even if naming it fails, and saving
        # again would only find it.
        try:
            gam.update(asset.id, changes)
        except GamError:
            pass
    finally:
        gam.close()

    job.gam_asset_id = asset.id
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
