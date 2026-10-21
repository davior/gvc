"""Generating pictures and clips for a project's placeholders, through GAM.

A generation runs in GAM; reading a project's generations is what follows them, with
the reader's token. So a generation started and left is caught up whenever the project
is next looked at, and nothing in GVC has to stay running for it.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import CallerToken, CurrentUser
from app.database import get_session
from app.gam.client import GamClient, GamError
from app.generation import service
from app.generation.catalogue import KINDS, price_line
from app.models.generation import Generation
from app.schemas import DataResponse, ListResponse
from app.services import projects as project_service

router = APIRouter()


class GenerationCreate(BaseModel):
    asset_key: str
    prompt: Optional[str] = Field(default=None, max_length=4000)
    model_id: Optional[str] = None
    outputs: int = Field(default=1, ge=1, le=4)
    duration: Optional[str] = None
    base_gam_ids: List[str] = []
    # A clip from the prompt alone: generate its picture first, then animate that.
    make_picture: bool = False
    picture_prompt: Optional[str] = Field(default=None, max_length=4000)
    picture_model_id: Optional[str] = None
    # The editor's draft: a placeholder made by hand is generated before it is saved.
    draft_spec: Optional[Dict[str, Any]] = None


class GenerationUse(BaseModel):
    asset_id: str


class GenerationRead(BaseModel):
    id: str
    project_id: Optional[str] = None
    asset_key: str
    kind: str
    prompt: str
    model_label: str
    status: str
    stage: str
    progress: int
    detail: str
    error: Optional[str] = None
    result_ids: List[str] = []
    used_id: Optional[str] = None
    # A list price from GAM's catalogue: an estimate, never a bill.
    estimate: Optional[float] = None
    # The picture a clip was made from, when it was generated for it.
    picture_id: Optional[str] = None


class GenerationModelRead(BaseModel):
    id: str
    kind: str
    label: str
    note: str = ""
    price: str
    unit_price: Optional[float] = None
    price_unit: Optional[str] = None
    options: Dict[str, Any] = {}


def read(row: Generation) -> GenerationRead:
    return GenerationRead(
        id=row.id, project_id=row.project_id, asset_key=row.asset_key, kind=row.kind,
        prompt=row.prompt, model_label=row.model_label, status=row.status, stage=row.stage,
        progress=row.progress, detail=row.detail, error=row.error,
        result_ids=json.loads(row.result_ids or "[]"), used_id=row.used_id,
        estimate=row.estimate, picture_id=row.picture_id,
    )


def _gam_failed(exc: GamError) -> HTTPException:
    return HTTPException(status_code=exc.status_code,
                         detail={"code": exc.code, "message": exc.message})


def _owned(session: Session, user, generation_id: str) -> Generation:
    row = session.get(Generation, generation_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": "Generation not found"})
    return row


@router.get("/gam/generation-models", response_model=ListResponse[GenerationModelRead])
def list_models(user: CurrentUser, token: CallerToken) -> ListResponse[GenerationModelRead]:
    """GAM's catalogue, for the kinds GVC generates, with the price a person reads."""
    gam = GamClient(token)
    try:
        models = gam.generation_models()
    except GamError as exc:
        raise _gam_failed(exc)
    finally:
        gam.close()
    wanted = set(KINDS.values()) | {"image_to_image"}
    rows = [GenerationModelRead(id=m["id"], kind=m["kind"], label=m.get("label") or "",
                                note=m.get("note") or "", price=price_line(m),
                                unit_price=m.get("unit_price"), price_unit=m.get("price_unit"),
                                options=m.get("options") or {})
            for m in models if m.get("kind") in wanted]
    return ListResponse(data=rows, total=len(rows), limit=len(rows), offset=0)


@router.post("/projects/{project_id}/generations", response_model=DataResponse[GenerationRead],
             status_code=status.HTTP_202_ACCEPTED)
def start_generation(project_id: str, body: GenerationCreate, user: CurrentUser,
                     token: CallerToken, session: Session = Depends(get_session)
                     ) -> DataResponse[GenerationRead]:
    project = project_service.get_owned(session, user, project_id)
    spec = body.draft_spec if body.draft_spec is not None else project_service.decode(project.spec)
    gam = GamClient(token)
    try:
        row = service.start(session, gam, user_id=user.id, project_id=project.id, turn_id=None,
                            spec=spec, key=body.asset_key, prompt=body.prompt,
                            model_id=body.model_id, outputs=body.outputs, duration=body.duration,
                            base_gam_ids=body.base_gam_ids, make_picture=body.make_picture,
                            picture_prompt=body.picture_prompt,
                            picture_model_id=body.picture_model_id)
    except service.GenerationRefused as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": exc.code, "message": exc.message})
    except GamError as exc:
        raise _gam_failed(exc)
    finally:
        gam.close()
    return DataResponse(data=read(row))


@router.get("/projects/{project_id}/generations", response_model=ListResponse[GenerationRead])
def list_generations(project_id: str, user: CurrentUser, token: CallerToken,
                     session: Session = Depends(get_session)) -> ListResponse[GenerationRead]:
    """The project's generations, the unfinished ones first brought up to date."""
    project = project_service.get_owned(session, user, project_id)
    rows = list(session.exec(select(Generation).where(Generation.project_id == project.id)
                             .order_by(Generation.created_at)).all())
    gam = GamClient(token)
    try:
        service.refresh(session, gam, rows)
    finally:
        gam.close()
    return ListResponse(data=[read(r) for r in rows], total=len(rows), limit=len(rows), offset=0)


@router.post("/generations/{generation_id}/use", response_model=DataResponse[GenerationRead])
def use_output(generation_id: str, body: GenerationUse, user: CurrentUser,
               session: Session = Depends(get_session)) -> DataResponse[GenerationRead]:
    """Record which output fills the placeholder (the editor puts it in the draft)."""
    row = _owned(session, user, generation_id)
    if body.asset_id not in json.loads(row.result_ids or "[]"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"code": "not_an_output",
                                    "message": "That asset isn't one this generation made"})
    row.used_id = body.asset_id
    session.add(row)
    session.commit()
    session.refresh(row)
    return DataResponse(data=read(row))


@router.delete("/generations/{generation_id}", response_model=DataResponse[GenerationRead])
def cancel_generation(generation_id: str, user: CurrentUser, token: CallerToken,
                      session: Session = Depends(get_session)) -> DataResponse[GenerationRead]:
    row = _owned(session, user, generation_id)
    gam = GamClient(token)
    try:
        service.cancel(session, gam, row)
    except GamError as exc:
        raise _gam_failed(exc)
    finally:
        gam.close()
    return DataResponse(data=read(row))
