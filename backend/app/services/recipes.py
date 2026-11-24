"""Recipes: their placeholders, running one, and the rules both the API and the assistant
keep when one is saved.

Placeholders are Gecko Notes' (`frontend/src/utils/recipeVariables.ts` there), so a recipe
imported from Notes reads the same way: `{{ name }}`, matched ignoring case, spaces, `_`
and `-`, and one with no value is left as typed so it shows that it wasn't filled. Here
they are filled on the server, not in the browser, because a run is a turn the server
starts, and what the model is asked must not depend on which client asked it.
`frontend/src/recipes/variables.ts` mirrors this for the run form and the editor.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.clock import utcnow
from app.models.recipe import Recipe
from app.schemas_recipes import MAX_RECIPE_TAGS, MAX_TAG, RecipeDefaults, RecipeRead
from app.services import themes as theme_service

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

# Filled in by the run, never asked for. `title` is the open video's (Notes' was the note's,
# hence the alias); `date` and `time` are the asker's own clock when the browser sends them.
BUILTIN_ALIASES = {"title": "title", "videotitle": "title", "projecttitle": "title",
                   "notetitle": "title", "date": "date", "time": "time"}


def normalize(key: str) -> str:
    return re.sub(r"[\s_-]+", "", key).lower()


def placeholders(prompt: str) -> List[str]:
    """Every distinct placeholder, as first written, in order."""
    seen, found = set(), []
    for match in PLACEHOLDER.finditer(prompt or ""):
        key = normalize(match.group(1))
        if key and key not in seen:
            seen.add(key)
            found.append(match.group(1).strip())
    return found


def inputs_of(prompt: str) -> List[str]:
    """The placeholders a run asks for: all but the built-ins."""
    return [p for p in placeholders(prompt) if normalize(p) not in BUILTIN_ALIASES]


def render(prompt: str, values: Dict[str, str]) -> str:
    """The prompt with each placeholder that has a non-empty value filled in."""
    table = {normalize(k): v.strip() for k, v in values.items()
             if isinstance(v, str) and v.strip()}
    for alias, target in BUILTIN_ALIASES.items():
        if alias not in table and target in table:
            table[alias] = table[target]

    def fill(match: re.Match) -> str:
        key = normalize(match.group(1))
        return table[key] if key in table else match.group(0)

    return PLACEHOLDER.sub(fill, prompt or "")


def clean_tags(tags: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        tag = tag.strip().lower()[:MAX_TAG]
        if tag and tag not in out:
            out.append(tag)
    return out[:MAX_RECIPE_TAGS]


def decode_defaults(raw: Optional[str]) -> RecipeDefaults:
    try:
        return RecipeDefaults.model_validate(json.loads(raw or "{}"))
    except (ValueError, TypeError):
        # A stored value written by an older shape: no defaults rather than an error.
        return RecipeDefaults()


def encode_defaults(defaults: RecipeDefaults) -> str:
    return json.dumps(defaults.model_dump(mode="json", exclude_none=True), ensure_ascii=False)


def read(row: Recipe) -> RecipeRead:
    return RecipeRead(id=row.id, name=row.name, prompt=row.prompt,
                      tags=json.loads(row.tags or "[]"), defaults=decode_defaults(row.defaults),
                      inputs=inputs_of(row.prompt), sort_order=row.sort_order,
                      created_at=row.created_at, updated_at=row.updated_at)


def listed(session: Session, user_id: str) -> List[Recipe]:
    return list(session.exec(select(Recipe).where(Recipe.user_id == user_id)
                             .order_by(Recipe.sort_order, Recipe.name)).all())


def owned(session: Session, user_id: str, recipe_id: Optional[str]) -> Optional[Recipe]:
    if not recipe_id:
        return None
    row = session.get(Recipe, recipe_id)
    return row if row is not None and row.user_id == user_id else None


def refused(code: str, message: str,
            status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def check_defaults(session: Session, user_id: str, defaults: RecipeDefaults) -> None:
    """A theme must be the caller's own: an id from anyone else's list would silently
    style nothing, which is the rule `style.theme` keeps too."""
    if defaults.theme_id and theme_service.owned(session, user_id, defaults.theme_id) is None:
        raise refused("unknown_theme", "That theme isn't one of yours")


def save(session: Session, row: Recipe, *, name: Optional[str] = None,
         prompt: Optional[str] = None, tags: Optional[List[str]] = None,
         defaults: Optional[RecipeDefaults] = None,
         sort_order: Optional[int] = None) -> Recipe:
    """Write a recipe; None leaves a field alone. Shared by the API and the assistant's
    Save button, so both keep the same rules."""
    if defaults is not None:
        check_defaults(session, row.user_id, defaults)
        row.defaults = encode_defaults(defaults)
    if name is not None:
        row.name = name.strip()
    if prompt is not None:
        row.prompt = prompt.strip()
    if tags is not None:
        row.tags = json.dumps(clean_tags(tags), ensure_ascii=False)
    if sort_order is not None:
        row.sort_order = sort_order
    if not row.name or not row.prompt:
        raise refused("invalid_recipe", "A recipe needs a name and a prompt")
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def apply_defaults(data: Dict[str, Any], defaults: RecipeDefaults) -> Dict[str, Any]:
    """A starter spec (as JSON) with the recipe's defaults on it.

    Only ever for a video made from scratch: on an open video the defaults are told to the
    model instead (assistant/prompt.py), because changing its format here would be a
    change nobody pressed Apply on.
    """
    out = json.loads(json.dumps(data))
    if defaults.theme_id:
        out.setdefault("style", {})["theme"] = defaults.theme_id
    if defaults.aspect:
        out.setdefault("output", {})["aspect"] = defaults.aspect
    if defaults.voice is not None:
        voice = out.setdefault("voice", {})
        voice.update(defaults.voice.model_dump(mode="json", exclude_none=True))
    return out


def describe_defaults(defaults: RecipeDefaults, theme_names: Dict[str, str]) -> str:
    """The defaults in a few words, for the model and for step lines."""
    parts = []
    if defaults.theme_id:
        parts.append(f"theme {theme_names.get(defaults.theme_id, '(deleted)')!r}")
    if defaults.aspect:
        parts.append(f"aspect {defaults.aspect}")
    if defaults.voice is not None:
        voice = defaults.voice.model_dump(exclude_none=True)
        if voice:
            parts.append("voice " + ", ".join(f"{k} {v}" for k, v in voice.items()))
    return "; ".join(parts)
