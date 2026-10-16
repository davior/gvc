"""Recording what a call consumed, and reading it back as totals.

Copied from GAM's `app/usage/events.py`, attributed to projects and assistant turns
instead of assets. Best-effort by design: a failure to write a usage row must never fail
the work that produced it.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, func, select

from app.models.usage import KIND_AI, UNIT_TOKENS, UsageEvent
from app.usage import pricing

logger = logging.getLogger(__name__)


def record_reply(session: Session, *, user_id: str, project_id: Optional[str],
                 turn_id: Optional[str], reply) -> Optional[float]:
    """Record one LLM call from the `Reply` its provider returned. Never raises.

    Returns the estimated cost (None when it cannot be priced), so the turn can keep a
    running total without reading the rows back.
    """
    try:
        tokens_in, tokens_out = reply.usage.input_tokens, reply.usage.output_tokens
        if tokens_in + tokens_out <= 0:
            # A provider that reported nothing. A zero-token row would suggest a free
            # call rather than an unmeasured one.
            return None
        estimate = pricing.cost_for(reply.provider_type, reply.model, tokens_in, tokens_out)
        session.add(UsageEvent(
            user_id=user_id, project_id=project_id, turn_id=turn_id, kind=KIND_AI,
            provider=reply.provider_type, model=reply.model or "",
            units=tokens_in + tokens_out, unit_type=UNIT_TOKENS,
            cost=estimate[0] if estimate else None, currency=estimate[1] if estimate else None,
            cost_estimated=True if estimate else None,
        ))
        session.commit()
        return estimate[0] if estimate else None
    except Exception:  # noqa: BLE001 - accounting must not break the work it measures
        logger.warning("Could not record usage for %s", user_id, exc_info=True)
        session.rollback()
        return None


def totals_for(session: Session, user_id: str, project_id: Optional[str] = None) -> dict:
    """What has been spent, overall or on one project.

    `priced_events` and `total_events` are reported apart on purpose: when they differ,
    some calls could not be priced, and a total that silently left them out would read
    as complete.
    """
    where = [UsageEvent.user_id == user_id]
    if project_id is not None:
        where.append(UsageEvent.project_id == project_id)
    rows = session.exec(select(UsageEvent).where(*where)).all()
    priced = [r for r in rows if r.cost is not None]
    return {
        "total_events": len(rows),
        "priced_events": len(priced),
        "cost": round(sum(r.cost or 0.0 for r in priced), 6) if priced else 0.0,
        "currency": next((r.currency for r in priced if r.currency), "USD"),
        "estimated": True,
        "tokens": sum(r.units for r in rows if r.unit_type == UNIT_TOKENS),
    }


def by_provider(session: Session, user_id: str) -> list[dict]:
    """Spend grouped by provider and model, biggest first."""
    rows = session.exec(
        select(UsageEvent.provider, UsageEvent.model, func.count(UsageEvent.id),
               func.sum(UsageEvent.units), func.sum(UsageEvent.cost))
        .where(UsageEvent.user_id == user_id)
        .group_by(UsageEvent.provider, UsageEvent.model)
    ).all()
    grouped = [
        {"provider": provider or "unknown", "model": model or "", "events": int(events or 0),
         "units": int(units or 0), "cost": round(float(cost), 6) if cost is not None else None}
        for provider, model, events, units, cost in rows
    ]
    grouped.sort(key=lambda g: (g["cost"] or 0.0), reverse=True)
    return grouped
