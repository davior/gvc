"""The theme list: named prompt modifiers, and which one new projects start with."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session

from app.auth import CurrentUser
from app.database import get_session
from app.models.theme import Theme
from app.schemas import DataResponse, ListResponse
from app.schemas_themes import ThemeCreate, ThemeRead, ThemeUpdate
from app.services import themes as service
from app.services.users import ensure_user

router = APIRouter()


def _owned(session: Session, user_id: str, theme_id: str) -> Theme:
    row = service.owned(session, user_id, theme_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": "Theme not found"})
    return row


def _read(row: Theme) -> ThemeRead:
    return ThemeRead.model_validate(row)


@router.get("", response_model=ListResponse[ThemeRead])
def list_themes(user: CurrentUser, session: Session = Depends(get_session)
                ) -> ListResponse[ThemeRead]:
    rows = service.listed(session, user.id)
    return ListResponse(data=[_read(r) for r in rows], total=len(rows), limit=len(rows),
                        offset=0)


@router.post("", response_model=DataResponse[ThemeRead], status_code=status.HTTP_201_CREATED)
def create_theme(body: ThemeCreate, user: CurrentUser,
                 session: Session = Depends(get_session)) -> DataResponse[ThemeRead]:
    ensure_user(session, user)
    row = Theme(id=str(uuid.uuid4()), user_id=user.id, name=body.name.strip(),
                prompt=body.prompt.strip(), is_default=body.is_default)
    if row.is_default:
        service.clear_default(session, user.id, keep=None)
    session.add(row)
    session.commit()
    session.refresh(row)
    return DataResponse(data=_read(row))


@router.put("/{theme_id}", response_model=DataResponse[ThemeRead])
def update_theme(theme_id: str, body: ThemeUpdate, user: CurrentUser,
                 session: Session = Depends(get_session)) -> DataResponse[ThemeRead]:
    """Edits apply to every project using the theme, from its next generation on.
    What was already generated keeps the look it was made with."""
    row = service.update(session, _owned(session, user.id, theme_id), name=body.name,
                         prompt=body.prompt, is_default=body.is_default)
    return DataResponse(data=_read(row))


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               response_class=Response)
def delete_theme(theme_id: str, user: CurrentUser,
                 session: Session = Depends(get_session)) -> None:
    """Projects naming it aren't rewritten: an id with no theme reads as no theme
    (services/themes.py), and rewriting every spec would put a version in each one's
    history that nobody made."""
    session.delete(_owned(session, user.id, theme_id))
    session.commit()
