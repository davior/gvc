"""What each call to a paid service cost, so GVC can answer "how much".

Copied from GAM (`app/models/usage.py`), which ported it from gecko-notes, with
`project_id` in place of GAM's `asset_id`: spend is attributed to the video it was spent
on. A plain indexed column and not a foreign key, on purpose: deleting a project must
not delete the record of what was spent on it.

The field that matters most is `cost_estimated`. A figure from `usage/pricing.py` is a
published list price, not a bill, and nothing may show a cost without saying so.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.clock import utcnow

# Only the assistant spends in GVC so far. Narration is read through Notes and billed
# there, so it is never counted here twice.
KIND_AI = "ai"

UNIT_TOKENS = "tokens"


def new_usage_id() -> str:
    return str(uuid.uuid4())


class UsageEvent(SQLModel, table=True):
    __table_args__ = (Index("ix_usageevent_user_created", "user_id", "created_at"),)

    id: str = Field(default_factory=new_usage_id, primary_key=True)
    user_id: str = Field(index=True)
    # Nullable: a draft from the project list has no project until it is applied. No
    # foreign key, on purpose: see the module docstring.
    project_id: Optional[str] = Field(default=None, index=True)

    kind: str = Field(index=True)
    # The provider's own type, not the protocol it spoke. A DeepSeek provider addressed
    # over the Anthropic endpoint is DeepSeek spend, and costing it as Anthropic would be
    # wrong by an order of magnitude.
    provider: Optional[str] = Field(default=None, index=True)
    model: str = Field(default="")

    units: int = Field(default=0)
    unit_type: str = Field(default="")

    # None when no estimate is possible — a `custom` endpoint, or a model family the
    # table does not know. Storing a zero there would read as "this was free".
    cost: Optional[float] = None
    currency: Optional[str] = None
    # True for a list-price estimate, which is all GVC records.
    cost_estimated: Optional[bool] = None
    # The assistant turn the call belonged to, so a turn's cost is one sum.
    turn_id: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)
