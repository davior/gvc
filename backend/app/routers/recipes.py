"""The recipe list: saved prompts with inputs, run through the assistant.

There is no run route here. A run is an assistant turn (`POST /api/assistant/turns` with
`recipe_id`), so it is followed, stopped and applied the way every request is.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from app.auth import CurrentUser
from app.database import get_session
from app.models.recipe import Recipe
from app.schemas import DataResponse, ListResponse
from app.schemas_recipes import (
    RecipeCreate, RecipeDefaults, RecipeImport, RecipeImportRead, RecipeRead, RecipeUpdate,
)
from app.services import recipes as service
from app.services import themes
from app.services.users import ensure_user

router = APIRouter()


def _owned(session: Session, user_id: str, recipe_id: str) -> Recipe:
    row = service.owned(session, user_id, recipe_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": "Recipe not found"})
    return row


@router.get("", response_model=ListResponse[RecipeRead])
def list_recipes(user: CurrentUser, session: Session = Depends(get_session)
                 ) -> ListResponse[RecipeRead]:
    rows = service.listed(session, user.id)
    return ListResponse(data=[service.read(r) for r in rows], total=len(rows),
                        limit=len(rows), offset=0)


@router.get("/{recipe_id}", response_model=DataResponse[RecipeRead])
def get_recipe(recipe_id: str, user: CurrentUser,
               session: Session = Depends(get_session)) -> DataResponse[RecipeRead]:
    return DataResponse(data=service.read(_owned(session, user.id, recipe_id)))


@router.post("", response_model=DataResponse[RecipeRead], status_code=status.HTTP_201_CREATED)
def create_recipe(body: RecipeCreate, user: CurrentUser,
                  session: Session = Depends(get_session)) -> DataResponse[RecipeRead]:
    ensure_user(session, user)
    row = Recipe(id=str(uuid.uuid4()), user_id=user.id, name="", prompt="")
    row = service.save(session, row, name=body.name, prompt=body.prompt, tags=body.tags,
                       defaults=body.defaults, sort_order=body.sort_order)
    return DataResponse(data=service.read(row))


@router.put("/{recipe_id}", response_model=DataResponse[RecipeRead])
def update_recipe(recipe_id: str, body: RecipeUpdate, user: CurrentUser,
                  session: Session = Depends(get_session)) -> DataResponse[RecipeRead]:
    """Videos already made from it are unaffected: a recipe is only read when it runs."""
    row = service.save(session, _owned(session, user.id, recipe_id), name=body.name,
                       prompt=body.prompt, tags=body.tags, defaults=body.defaults,
                       sort_order=body.sort_order)
    return DataResponse(data=service.read(row))


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               response_class=Response)
def delete_recipe(recipe_id: str, user: CurrentUser,
                  session: Session = Depends(get_session)) -> None:
    """Projects made from it keep naming it in `source.recipe`: provenance, not a link."""
    session.delete(_owned(session, user.id, recipe_id))
    session.commit()


@router.post("/import", response_model=DataResponse[RecipeImportRead], status_code=status.HTTP_201_CREATED)
def import_recipes(body: RecipeImport, user: CurrentUser,
                   session: Session = Depends(get_session)) -> DataResponse[RecipeImportRead]:
    """Add an exported list, from here or from Gecko Notes.

    One that is already in the list (same name and prompt) is skipped, so importing a file
    twice doesn't double it; one naming a theme that isn't the importer's keeps its other
    settings and loses the theme, which is said, rather than refusing the whole file.
    """
    ensure_user(session, user)
    existing = {(r.name.strip().lower(), r.prompt.strip()) for r in service.listed(session, user.id)}
    made, skipped = [], []
    for item in body.recipes:
        key = (item.name.strip().lower(), item.prompt.strip())
        if key in existing:
            skipped.append(f"{item.name!r} is already in your recipes.")
            continue
        defaults = item.defaults or RecipeDefaults()
        if defaults.theme_id and themes.owned(session, user.id, defaults.theme_id) is None:
            defaults = defaults.model_copy(update={"theme_id": None})
            skipped.append(f"{item.name!r}: its theme isn't one of yours, so it has none.")
        row = Recipe(id=str(uuid.uuid4()), user_id=user.id, name="", prompt="")
        made.append(service.save(session, row, name=item.name, prompt=item.prompt,
                                 tags=item.tags, defaults=defaults))
        existing.add(key)
    return DataResponse(data=RecipeImportRead(imported=len(made), skipped=skipped,
                                              recipes=[service.read(r) for r in made]))
