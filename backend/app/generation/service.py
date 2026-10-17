"""Starting, following and stopping generations for `generate` placeholders."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.clock import utcnow
from app.gam.client import GamClient, GamError
from app.generation.catalogue import CatalogueError, default_params, estimate, kind_for, pick_model
from app.models.generation import Generation

logger = logging.getLogger(__name__)

FINAL = ("done", "error", "cancelled")


class GenerationRefused(Exception):
    """The placeholder can't be generated as asked; the message says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def placeholder(spec: Dict[str, Any], key: str) -> Dict[str, Any]:
    ref = (spec.get("assets") or {}).get(key)
    if not isinstance(ref, dict) or ref.get("from") != "generate":
        raise GenerationRefused("not_a_placeholder",
                                f"{key!r} is not a picture or clip waiting to be generated.")
    if ref.get("type") not in ("image", "video"):
        raise GenerationRefused("cannot_generate",
                                "Only pictures and video can be generated; music and sound "
                                "effects have to come from your library.")
    return ref


def _gam_id_of(spec: Dict[str, Any], key: str) -> Optional[str]:
    ref = (spec.get("assets") or {}).get(key) or {}
    if ref.get("from") == "gam":
        return ref.get("id")
    result = ref.get("result") or {}
    return result.get("id")


def start(session: Session, gam: GamClient, *, user_id: str, project_id: Optional[str],
          turn_id: Optional[str], spec: Dict[str, Any], key: str,
          prompt: Optional[str] = None, model_id: Optional[str] = None, outputs: int = 1,
          duration: Optional[str] = None,
          base_gam_ids: Optional[List[str]] = None) -> Generation:
    ref = placeholder(spec, key)
    prompt = (prompt or ref.get("prompt") or "").strip()
    if not prompt:
        raise GenerationRefused("no_prompt", "Say what to generate first.")
    bases = list(base_gam_ids or [])
    if not bases:
        bases = [gid for gid in (_gam_id_of(spec, k) for k in ref.get("base_assets") or []) if gid]
    if ref["type"] == "video" and not bases:
        raise GenerationRefused("needs_base_image",
                                "A clip is made from a picture: choose the picture to start from.")
    try:
        kind = kind_for(ref["type"], bool(bases))
        model = pick_model(gam.generation_models(), kind, model_id)
    except CatalogueError as exc:
        raise GenerationRefused("no_model", str(exc))
    aspect = ref.get("aspect") or (spec.get("output") or {}).get("aspect") or "16:9"
    params = default_params(model, aspect=aspect, outputs=outputs if ref["type"] == "image" else 1,
                            duration=duration)
    job = gam.start_generation(model_id=model["id"], prompt=prompt,
                               base_ids=bases[:1] if kind == "image_to_video" else bases,
                               params=params)
    row = Generation(id=str(uuid.uuid4()), user_id=user_id, project_id=project_id,
                     turn_id=turn_id, asset_key=key, gam_job_id=job["id"], kind=kind,
                     prompt=prompt, model_label=model.get("label") or model.get("endpoint_id", ""),
                     params=json.dumps(params), status=job.get("status") or "queued",
                     stage=job.get("stage") or "", progress=job.get("progress") or 0,
                     estimate=estimate(model, params))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def refresh(session: Session, gam: GamClient, rows: List[Generation]) -> None:
    """Ask GAM about every unfinished generation. Best effort: GAM being unreachable
    leaves the rows as they were, to be caught up on the next read."""
    changed = False
    for row in rows:
        if row.status in FINAL:
            continue
        try:
            job = gam.generation_job(row.gam_job_id)
        except GamError as exc:
            logger.info("Could not follow generation %s: %s", row.id, exc.message)
            return
        if job is None:
            row.status, row.error = "error", "The asset library no longer has this generation."
        else:
            row.status = job.get("status") or row.status
            row.stage = job.get("stage") or ""
            row.progress = int(job.get("progress") or 0)
            row.detail = job.get("detail") or ""
            row.error = job.get("error_message")
            ids = job.get("result_asset_ids") or ([job["result_asset_id"]]
                                                  if job.get("result_asset_id") else [])
            row.result_ids = json.dumps(ids)
        row.updated_at = utcnow()
        session.add(row)
        changed = True
    if changed:
        session.commit()


def cancel(session: Session, gam: GamClient, row: Generation) -> None:
    if row.status in FINAL:
        return
    gam.cancel_generation(row.gam_job_id)
    row.status, row.stage, row.updated_at = "cancelled", "", utcnow()
    session.add(row)
    session.commit()
