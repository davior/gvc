"""Wire shapes for the recipe list."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.spec.model import Aspect, VoiceOverride

MAX_RECIPE_NAME = 120
# Room for a detailed brief. A run's prompt is this with its inputs filled in, and has to
# fit a turn's own 20,000 (schemas_assistant.TurnCreate).
MAX_RECIPE_PROMPT = 10_000
MAX_RECIPE_TAGS = 12
MAX_TAG = 40
MAX_INPUT_CHARS = 4_000
MAX_IMPORT = 200


class RecipeDefaults(BaseModel):
    """What a video made from the recipe starts with. Every field is optional, and the
    values are the spec's own types, so a recipe can't carry a setting the spec rejects."""

    model_config = ConfigDict(extra="forbid")

    theme_id: Optional[str] = Field(default=None, max_length=64)
    aspect: Optional[Aspect] = None
    # A partial voice, merged over the starter's: VoiceOverride is the spec's partial voice.
    voice: Optional[VoiceOverride] = None


class RecipeRead(BaseModel):
    id: str
    name: str
    prompt: str
    tags: List[str]
    defaults: RecipeDefaults
    # The placeholders the run form asks for: every one except the built-ins.
    inputs: List[str]
    sort_order: int
    created_at: datetime
    updated_at: datetime


class RecipeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_RECIPE_NAME)
    prompt: str = Field(min_length=1, max_length=MAX_RECIPE_PROMPT)
    tags: List[str] = Field(default_factory=list, max_length=MAX_RECIPE_TAGS)
    defaults: RecipeDefaults = Field(default_factory=RecipeDefaults)
    sort_order: int = 0


class RecipeUpdate(BaseModel):
    """Fields left out are left alone."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=MAX_RECIPE_NAME)
    prompt: Optional[str] = Field(default=None, min_length=1, max_length=MAX_RECIPE_PROMPT)
    tags: Optional[List[str]] = Field(default=None, max_length=MAX_RECIPE_TAGS)
    defaults: Optional[RecipeDefaults] = None
    sort_order: Optional[int] = None


class RecipeImportItem(BaseModel):
    """One entry of an exported list. Gecko Notes' export is `[{name, prompt, tags}]`,
    so a file from there imports as it is; unknown keys are ignored for the same reason."""

    name: str = Field(min_length=1, max_length=MAX_RECIPE_NAME)
    prompt: str = Field(min_length=1, max_length=MAX_RECIPE_PROMPT)
    tags: List[str] = Field(default_factory=list)
    defaults: Optional[RecipeDefaults] = None


class RecipeImport(BaseModel):
    recipes: List[RecipeImportItem] = Field(max_length=MAX_IMPORT)


class RecipeImportRead(BaseModel):
    imported: int
    # A sentence per entry left out, e.g. a theme that isn't the importer's.
    skipped: List[str] = []
    recipes: List[RecipeRead] = []
