"""A recipe: a saved prompt with `{{inputs}}`, run to make or change a video.

Gecko Notes' recipe, carried over: a reusable request, so a kind of video someone makes
often ("a 60-second explainer about {{topic}}") is asked the same way every time. Here it
can also carry the settings a video of that kind starts with (`defaults`).

A recipe is a library entry, like a theme, not part of a video. Running one is an
ordinary assistant turn (routers/assistant.py), so a video made from a recipe is an
ordinary project that only names it as provenance (`source.recipe`), and editing or
deleting the recipe afterwards changes nothing already made.

Per user, as themes are, for the same reason: there is no admin role to own a shared list.
"""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.clock import utcnow


class Recipe(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    # The request, with `{{placeholders}}` (services/recipes.py): the built-ins are filled
    # in when it runs, and every other one is asked for in the run form.
    prompt: str
    # JSON array of lowercase strings, for filtering the list.
    tags: str = "[]"
    # JSON: {"theme_id"?, "aspect"?, "voice"?}. Applied only to a video made from scratch,
    # never to one that is open (services/recipes.apply_defaults).
    defaults: str = "{}"
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
