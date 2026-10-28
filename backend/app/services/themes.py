"""Themes: which one a spec names, and what it does to a prompt.

A spec names its theme by id (`style.theme`). The id is only meaningful against the
owner's own list, so it is always resolved through `owned`: a theme since deleted, or
an id that came in on a spec pasted from someone else, reads as no theme rather than
as an error. Nothing about a video breaks when its theme goes away; its next
generation is just unstyled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models.theme import Theme
from app.spec.model import VideoSpec


def listed(session: Session, user_id: str) -> List[Theme]:
    return list(session.exec(select(Theme).where(Theme.user_id == user_id)
                             .order_by(Theme.name)).all())


def owned(session: Session, user_id: str, theme_id: Optional[str]) -> Optional[Theme]:
    if not theme_id:
        return None
    row = session.get(Theme, theme_id)
    return row if row is not None and row.user_id == user_id else None


def default_for(session: Session, user_id: str) -> Optional[Theme]:
    return session.exec(select(Theme).where(Theme.user_id == user_id,
                                            Theme.is_default == True)  # noqa: E712
                        ).first()


def theme_id_of(data: Dict[str, Any]) -> Optional[str]:
    """The theme a spec (as JSON) names. Read loosely: generation is given unsaved
    drafts, which are not guaranteed to be well formed."""
    style = data.get("style") if isinstance(data, dict) else None
    value = style.get("theme") if isinstance(style, dict) else None
    return value if isinstance(value, str) and value else None


def of_spec(session: Session, user_id: str, data: Dict[str, Any]) -> Optional[Theme]:
    return owned(session, user_id, theme_id_of(data))


def styled(prompt: str, theme: Optional[Theme]) -> str:
    """The prompt as sent: the theme's modifier after the prompt, on its own paragraph.

    After, not before: image models weigh the start of a prompt most, and the subject
    of this picture matters more than the look shared by all of them.
    """
    modifier = (theme.prompt if theme else "").strip()
    prompt = prompt.strip()
    if not modifier:
        return prompt
    return f"{prompt}\n\n{modifier}" if prompt else modifier


def settle(session: Session, user_id: str, spec: VideoSpec, *, use_default: bool) -> None:
    """Give a project being created the theme it should start with.

    One the caller doesn't own is dropped. With none, `use_default` puts the user's
    default theme in. The assistant's drafts pass False: they started from a starter
    that already had the default, so a draft without one is one where it was taken out.
    """
    if spec.style.theme and owned(session, user_id, spec.style.theme) is None:
        spec.style.theme = None
    if spec.style.theme is None and use_default:
        default = default_for(session, user_id)
        if default is not None:
            spec.style.theme = default.id
