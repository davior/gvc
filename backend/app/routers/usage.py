"""What the assistant has spent, overall and per project.

Every figure is a list-price estimate (`usage/pricing.py`), and the response says so in
`estimated`, which the frontend is required to show.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import CurrentUser
from app.database import get_session
from app.schemas import DataResponse
from app.services import projects as project_service
from app.usage import events as usage_events

router = APIRouter()


class ProviderTotal(BaseModel):
    provider: str
    model: str
    events: int
    units: int
    cost: Optional[float] = None


class UsageTotals(BaseModel):
    total_events: int
    # Fewer than `total_events` means some calls could not be priced, so `cost` is a
    # floor rather than the whole story.
    priced_events: int
    cost: float
    currency: str
    estimated: bool
    tokens: int


class UsageSummary(BaseModel):
    totals: UsageTotals
    by_provider: list[ProviderTotal]


@router.get("", response_model=DataResponse[UsageSummary])
def read_usage(user: CurrentUser, session: Session = Depends(get_session)) -> DataResponse[UsageSummary]:
    return DataResponse(data=UsageSummary(
        totals=UsageTotals(**usage_events.totals_for(session, user.id)),
        by_provider=[ProviderTotal(**row) for row in usage_events.by_provider(session, user.id)],
    ))


@router.get("/projects/{project_id}", response_model=DataResponse[UsageTotals])
def read_project_usage(project_id: str, user: CurrentUser,
                       session: Session = Depends(get_session)) -> DataResponse[UsageTotals]:
    # Checked rather than trusted: a project id that is not yours should not be a way
    # to learn that it exists.
    project_service.get_owned(session, user, project_id)
    return DataResponse(data=UsageTotals(**usage_events.totals_for(session, user.id, project_id)))
