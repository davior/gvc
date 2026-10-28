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
from app.services import themes

logger = logging.getLogger(__name__)

FINAL = ("done", "error", "cancelled")

# GAM refuses a longer prompt (gam: app/generation/request.py, MAX_PROMPT_CHARS).
GAM_MAX_PROMPT = 4000


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
          base_gam_ids: Optional[List[str]] = None, make_picture: bool = False,
          picture_prompt: Optional[str] = None,
          picture_model_id: Optional[str] = None) -> Generation:
    """Start a placeholder's generation in GAM.

    `make_picture` makes a clip from a prompt alone: GAM has no text-to-video, so a
    picture is generated first and the clip is started from it by `refresh`, once the
    picture is done. One row follows both, so the editor sees one generation for the
    placeholder, and its price is the two together.
    """
    ref = placeholder(spec, key)
    prompt = (prompt or ref.get("prompt") or "").strip()
    if not prompt:
        raise GenerationRefused("no_prompt", "Say what to generate first.")
    # The project's theme is added here, on the way out, and never written into the
    # placeholder or the row: they keep the prompt as written, so "Try again" or a
    # reworded theme doesn't add it twice.
    theme = themes.of_spec(session, user_id, spec)
    sent = themes.styled(prompt, theme)
    picture_sent = themes.styled((picture_prompt or "").strip() or prompt, theme)
    if max(len(sent), len(picture_sent)) > GAM_MAX_PROMPT:
        added = f" with the theme “{theme.name}” added" if theme else ""
        raise GenerationRefused(
            "prompt_too_long",
            f"The prompt{added} is over the library's {GAM_MAX_PROMPT:,} characters. "
            "Shorten it" + (" or the theme." if theme else "."))
    chained = make_picture and ref["type"] == "video"
    bases = [] if chained else list(base_gam_ids or [])
    if not bases and not chained:
        bases = [gid for gid in (_gam_id_of(spec, k) for k in ref.get("base_assets") or []) if gid]
    if ref["type"] == "video" and not bases and not chained:
        raise GenerationRefused("needs_base_image",
                                "A clip is made from a picture: choose the picture to start from, "
                                "or have one made from the prompt.")
    aspect = ref.get("aspect") or (spec.get("output") or {}).get("aspect") or "16:9"
    try:
        models = gam.generation_models()
        kind = kind_for(ref["type"], bool(bases) or chained)
        model = pick_model(models, kind, model_id)
        picture_model = pick_model(models, "text_to_image", picture_model_id) if chained else None
    except CatalogueError as exc:
        raise GenerationRefused("no_model", str(exc))
    params = default_params(model, aspect=aspect, outputs=outputs if ref["type"] == "image" else 1,
                            duration=duration)
    label = model.get("label") or model.get("endpoint_id", "")
    cost = estimate(model, params)
    then = None
    if picture_model is not None:
        picture_params = default_params(picture_model, aspect=aspect, outputs=1)
        then = json.dumps({"model_id": model["id"], "model_label": label, "prompt": sent,
                           "params": params})
        picture_cost = estimate(picture_model, picture_params)
        cost = None if cost is None or picture_cost is None else round(cost + picture_cost, 4)
        label = f"{picture_model.get('label') or picture_model['id']} → {label}"
        job = gam.start_generation(model_id=picture_model["id"], prompt=picture_sent,
                                   base_ids=[], params=picture_params)
    else:
        job = gam.start_generation(model_id=model["id"], prompt=sent,
                                   base_ids=bases[:1] if kind == "image_to_video" else bases,
                                   params=params)
    row = Generation(id=str(uuid.uuid4()), user_id=user_id, project_id=project_id,
                     turn_id=turn_id, asset_key=key, gam_job_id=job["id"], kind=kind,
                     prompt=prompt, model_label=label, params=json.dumps(params),
                     status=job.get("status") or "queued",
                     stage=_stage(job.get("stage") or "", then), progress=job.get("progress") or 0,
                     estimate=cost, then=then)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _stage(stage: str, then: Optional[str]) -> str:
    """While the picture for a clip is being made, the stage says so."""
    if not then:
        return stage
    return f"Making the picture · {stage}" if stage else "Making the picture"


def _start_clip(gam: GamClient, row: Generation, ids: List[str]) -> None:
    """The picture is done: start the clip from it, on the same row."""
    then = json.loads(row.then or "{}")
    row.then = None
    if not ids:
        row.status, row.error = "error", "The picture came back empty, so no clip was made."
        return
    row.picture_id = ids[0]
    try:
        job = gam.start_generation(model_id=then["model_id"], prompt=then["prompt"],
                                   base_ids=[row.picture_id], params=then["params"])
    except GamError as exc:
        row.status = "error"
        row.error = f"The picture was made, but the clip couldn't be started: {exc.message}"
        return
    row.gam_job_id = job["id"]
    row.status = job.get("status") or "queued"
    row.stage = job.get("stage") or "Animating the picture"
    row.progress = int(job.get("progress") or 0)
    row.detail, row.error, row.result_ids = "", None, "[]"


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
            row.then = None
        else:
            ids = job.get("result_asset_ids") or ([job["result_asset_id"]]
                                                  if job.get("result_asset_id") else [])
            if row.then and job.get("status") == "done":
                # The picture's outputs are never the placeholder's: only the clip's are.
                _start_clip(gam, row, ids)
            else:
                row.status = job.get("status") or row.status
                row.stage = _stage(job.get("stage") or "", row.then)
                row.progress = int(job.get("progress") or 0)
                row.detail = job.get("detail") or ""
                row.error = job.get("error_message")
                if row.then and row.error:
                    row.error = f"Making the picture failed: {row.error}"
                if row.then is None:
                    row.result_ids = json.dumps(ids)
                if row.status in FINAL:
                    row.then = None
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
