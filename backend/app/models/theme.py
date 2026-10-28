"""A named look for what gets generated: a prompt modifier, per user.

A theme is a library entry, not part of a video. A project names one by id in its spec
(`style.theme`), so editing a theme changes what every project using it generates next,
which is the point of having a list rather than a style written into each project.

Per user rather than shared across the install, as providers are: there is no admin
role to own a shared list, and one person rewording "Noir" must not change what
another person's videos generate.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.clock import utcnow


class Theme(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    # Appended to every image and video prompt sent for a project using this theme,
    # after the prompt itself (generation/service.py).
    prompt: str = ""
    # The theme a new project starts with. At most one per user, kept so by the router
    # (the provider table's `is_active` rule, for the same reason).
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
