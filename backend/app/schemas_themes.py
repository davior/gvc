"""Wire shapes for the theme list."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Long enough for a paragraph of art direction, short enough that a theme can't crowd
# out the prompt it is added to: GAM takes 4000 characters for the two together.
MAX_THEME_PROMPT = 1500
MAX_THEME_NAME = 120


class ThemeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prompt: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ThemeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_THEME_NAME)
    prompt: str = Field(default="", max_length=MAX_THEME_PROMPT)
    is_default: bool = False


class ThemeUpdate(BaseModel):
    """Fields left out are left alone."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_THEME_NAME)
    prompt: Optional[str] = Field(default=None, max_length=MAX_THEME_PROMPT)
    is_default: Optional[bool] = None
