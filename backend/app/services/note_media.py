"""Moving a pushed note's pictures and sounds into GAM.

A note pushed from Notes arrives pointing at files inside the note (`from: "notes"`).
Copying them into GAM is what finishes the hand-off: afterwards the project depends on
the library, not on the note, which may be edited or deleted without touching the video.

Each ref is replaced under the same key, so every visual, overlay and track that used
it keeps working unchanged. Files are moved one at a time and the ones that fail stay
as they were, to be retried: one unreadable file must not lose the copies that worked.
"""

from __future__ import annotations

import logging
import mimetypes
import tempfile
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session

from app import outbound
from app.config import settings
from app.gam.client import GamClient, GamError
from app.models.project import Project
from app.services import projects as project_service
from app.spec.model import GamAsset, NotesAsset

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


class CopyFailed(Exception):
    pass


@dataclass
class CopyFailure:
    key: str
    message: str


@dataclass
class CopyResult:
    copied: List[str] = field(default_factory=list)
    failed: List[CopyFailure] = field(default_factory=list)


def _safe_path(url: str) -> str:
    """Only a path into Notes' own media, fetched only from the configured Notes.

    A spec can be pasted by anyone, so a `notes` ref's URL is untrusted input: taken as
    given, it would make this server fetch any address it was handed.
    """
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path.startswith("/media/") or ".." in parts.path:
        raise CopyFailed("Not a file in a note's media")
    return parts.path


def _fetch_to(path: str, sink) -> str:
    """Stream a Notes media file into `sink`, refusing past the size cap. Returns its
    content type."""
    limit = settings.note_media_max_mb * 1024 * 1024
    received = 0
    with outbound.client(settings.notes_base_url, timeout=120) as notes:
        try:
            with notes.stream("GET", path) as response:
                if response.status_code == 404:
                    raise CopyFailed("The note no longer has this file")
                if response.status_code != 200:
                    raise CopyFailed(f"Gecko Notes answered {response.status_code}")
                for chunk in response.iter_bytes(_CHUNK):
                    received += len(chunk)
                    if received > limit:
                        raise CopyFailed(f"Larger than {settings.note_media_max_mb} MB")
                    sink.write(chunk)
                return response.headers.get("content-type", "").split(";")[0].strip()
        except httpx.HTTPError as exc:
            raise CopyFailed("Could not reach Gecko Notes") from exc


def copy_note_media(session: Session, project: Project, gam: GamClient) -> CopyResult:
    spec = project_service.require_spec(project_service.decode(project.spec))
    result = CopyResult()

    for key, ref in list(spec.assets.items()):
        if not isinstance(ref, NotesAsset):
            continue
        try:
            path = _safe_path(ref.url)
            filename = path.rsplit("/", 1)[-1] or key
            with tempfile.TemporaryFile() as buffer:
                content_type = _fetch_to(path, buffer) or mimetypes.guess_type(filename)[0]
                buffer.seek(0)
                stored = gam.upload(filename, buffer, content_type)
        except CopyFailed as exc:
            result.failed.append(CopyFailure(key, str(exc)))
            continue
        except GamError as exc:
            result.failed.append(CopyFailure(key, exc.message))
            continue

        spec.assets[key] = GamAsset.model_validate({
            "from": "gam", "id": stored.id, "type": ref.type,
            "label": ref.label or stored.name,
        })
        result.copied.append(key)

    if result.copied:
        count = len(result.copied)
        project_service.save(
            session, project, spec,
            message=f"Copied {count} file{'' if count == 1 else 's'} from the note into GAM",
        )
    return result
