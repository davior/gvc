"""Running renders in the background, as the user who asked for them.

A render calls GAM (for media) and Notes (for narration) with the requester's own
token, so it can never reach what they could not. The token is held here, in memory,
for the job's life only. It is never written to the database: a 30-day credential at
rest is a worse problem than a render that has to be started again after a restart,
which is what `requeue_on_restart=False` makes happen.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from sqlmodel import Session, select

from app.config import settings
from app.gam.client import GamClient, GamError
from app.jobs.runner import JobCancelled, JobQueue, readable_error, set_fields
from app.models.project import Project, ProjectVersion
from app.models.render import RenderJob
from app.render.renderer import RenderRefused, render
from app.render.tts import NotesSpeech, SpeechError
from app.spec.validation import parse_spec

logger = logging.getLogger(__name__)

_tokens: Dict[str, Optional[str]] = {}


def renders_dir() -> Path:
    return settings.resolved_data_dir / "renders"


def _run(job_id: str) -> None:
    with queue.session() as session:
        job = session.get(RenderJob, job_id)
        if job is None or job.status != "queued":
            return
        if job_id not in _tokens:
            set_fields(session, job, status="error",
                       error_message="Interrupted by a restart of the server. Start it again.")
            return
        version = session.exec(select(ProjectVersion).where(
            ProjectVersion.project_id == job.project_id,
            ProjectVersion.seq == job.version_seq)).first()
        if version is None:
            set_fields(session, job, status="error", error_message="That version no longer exists")
            return
        spec, issues = parse_spec(json.loads(version.spec))
        if spec is None:
            set_fields(session, job, status="error",
                       error_message="This version of the project no longer validates")
            return
        set_fields(session, job, status="processing", stage="Starting", progress=0)
        preview, user_id = job.preview, job.user_id

    token = _tokens.get(job_id)
    data_dir = settings.resolved_data_dir
    work_dir = data_dir / "work" / job_id
    out_dir = renders_dir() / job_id
    gam, speech = GamClient(token), NotesSpeech(token)
    try:
        result = render(
            spec=spec, preview=preview, work_dir=str(work_dir), out_dir=str(out_dir),
            data_dir=str(data_dir), user_id=user_id, gam=gam, speech=speech,
            progress=queue.reporter(job_id),
            max_segments=settings.render_max_segments,
            max_narration_chars=settings.render_max_narration_chars,
        )
    except JobCancelled:
        _finish(job_id, status="cancelled", stage="")
        shutil.rmtree(out_dir, ignore_errors=True)
    except (RenderRefused, SpeechError) as exc:
        _finish(job_id, status="error", stage="", error_message=str(exc))
        shutil.rmtree(out_dir, ignore_errors=True)
    except GamError as exc:
        _finish(job_id, status="error", stage="", error_message=exc.message)
        shutil.rmtree(out_dir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001 - a failed render is a job error, not a crash
        logger.exception("Render %s failed", job_id)
        _finish(job_id, status="error", stage="", error_message=readable_error(exc))
        shutil.rmtree(out_dir, ignore_errors=True)
    else:
        def rel(path: Optional[str]) -> Optional[str]:
            return Path(path).name if path else None

        _finish(job_id, status="done", stage="", progress=100, detail="",
                video_path=rel(result.video), subtitle_path=rel(result.subtitles),
                poster_path=rel(result.poster), duration=result.duration,
                size_bytes=result.size_bytes, narration_chars=result.narration_chars,
                warnings=json.dumps(result.warnings))
    finally:
        gam.close()
        speech.close()
        shutil.rmtree(work_dir, ignore_errors=True)
        _tokens.pop(job_id, None)


def _finish(job_id: str, **fields) -> None:
    with queue.session() as session:
        job = session.get(RenderJob, job_id)
        if job is not None:
            set_fields(session, job, **fields)


queue = JobQueue(RenderJob, _run, name="render", concurrency=settings.render_concurrency,
                 requeue_on_restart=False)


def submit(session: Session, project: Project, *, user_id: str, token: Optional[str],
           preview: bool) -> RenderJob:
    job = RenderJob(id=str(uuid.uuid4()), project_id=project.id, user_id=user_id,
                    version_seq=project.head_seq, preview=preview)
    session.add(job)
    session.commit()
    session.refresh(job)
    _tokens[job.id] = token
    queue.enqueue(job.id)
    return job


def start() -> None:
    queue.start()
