"""The assistant: start a turn, follow it, stop it, and act on what it proposes.

A turn is a background job, so none of this needs the page that started it to stay
open. `GET /turns?attention=1` is what the header asks to say "something is running, or
waiting for you", on any page.
"""

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, col, select

from app.assistant import worker
from app.auth import CallerToken, CurrentUser
from app.clock import utcnow
from app.database import get_session
from app.jobs.runner import ACTIVE_STATUSES
from app.models.assistant import AssistantSession, AssistantTurn
from app.providers import active_provider
from app.schemas import DataResponse, ListResponse
from app.schemas_assistant import (
    Message, NewProjectRead, SessionRead, SessionSummary, Step, TurnCreate, TurnRead,
)
from app.services import projects as project_service
from app.services.users import ensure_user
from app.spec.model import BriefSource, dump_spec
from app.spec.starter import starter_spec
from app.spec.validation import parse_spec

router = APIRouter()


def _turn_read(turn: AssistantTurn) -> TurnRead:
    proposal = json.loads(turn.proposed_spec) if turn.proposed_spec and \
        turn.outcome == "pending" else None
    return TurnRead(
        id=turn.id, session_id=turn.session_id, project_id=turn.project_id, status=turn.status,
        stage=turn.stage, detail=turn.detail, error=turn.error_message, prompt=turn.prompt,
        steps=[Step(**s) for s in json.loads(turn.steps or "[]")], reply=turn.reply,
        proposed_spec=proposal, changes=json.loads(turn.changes or "[]"), outcome=turn.outcome,
        base_version=turn.base_version, cost=turn.cost,
        created_at=turn.created_at, updated_at=turn.updated_at,
    )


def _summary(row: AssistantSession) -> SessionSummary:
    return SessionSummary(id=row.id, project_id=row.project_id, title=row.title or "New chat",
                          created_at=row.created_at, updated_at=row.updated_at)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                         detail={"code": "not_found", "message": f"{what} not found"})


def _owned_session(session: Session, user, session_id: str) -> AssistantSession:
    row = session.get(AssistantSession, session_id)
    if row is None or row.user_id != user.id:
        raise _not_found("Conversation")
    return row


def _owned_turn(session: Session, user, turn_id: str) -> AssistantTurn:
    row = session.get(AssistantTurn, turn_id)
    if row is None or row.user_id != user.id:
        raise _not_found("Turn")
    return row


# ── sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions", response_model=ListResponse[SessionSummary])
def list_sessions(user: CurrentUser, project_id: Optional[str] = None,
                  limit: int = Query(default=20, ge=1, le=100),
                  session: Session = Depends(get_session)) -> ListResponse[SessionSummary]:
    """A project's conversations, newest first; without a project, the ones about new
    videos not yet made."""
    if project_id:
        project_service.get_owned(session, user, project_id)
    where = AssistantSession.project_id == project_id if project_id else \
        col(AssistantSession.project_id).is_(None)
    rows = session.exec(select(AssistantSession).where(
        AssistantSession.user_id == user.id, where)
        .order_by(AssistantSession.updated_at.desc()).limit(limit)).all()
    return ListResponse(data=[_summary(r) for r in rows], total=len(rows), limit=limit, offset=0)


@router.get("/sessions/{session_id}", response_model=DataResponse[SessionRead])
def get_chat(session_id: str, user: CurrentUser,
             session: Session = Depends(get_session)) -> DataResponse[SessionRead]:
    row = _owned_session(session, user, session_id)
    turns = session.exec(select(AssistantTurn).where(AssistantTurn.session_id == row.id)
                         .order_by(AssistantTurn.created_at)).all()
    return DataResponse(data=SessionRead(
        **_summary(row).model_dump(),
        messages=[Message(**m) for m in json.loads(row.messages or "[]")],
        turns=[_turn_read(t) for t in turns],
        cost=round(sum(t.cost or 0.0 for t in turns), 6),
    ))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(session_id: str, user: CurrentUser,
                session: Session = Depends(get_session)) -> Response:
    row = _owned_session(session, user, session_id)
    turns = session.exec(select(AssistantTurn).where(AssistantTurn.session_id == row.id)).all()
    if any(t.status in ACTIVE_STATUSES for t in turns):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "turn_running", "message": "Stop the running turn first"})
    for turn in turns:
        session.delete(turn)
    session.flush()
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── turns ─────────────────────────────────────────────────────────────────────

@router.post("/turns", response_model=DataResponse[TurnRead], status_code=status.HTTP_202_ACCEPTED)
def start_turn(body: TurnCreate, user: CurrentUser, token: CallerToken,
               session: Session = Depends(get_session)) -> DataResponse[TurnRead]:
    """Ask the assistant something. It runs in the background from here."""
    if active_provider(session, user.id) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "no_provider",
                                    "message": "Set up an AI provider in Settings first."})
    project = project_service.get_owned(session, user, body.project_id) if body.project_id \
        else None
    if body.session_id:
        chat = _owned_session(session, user, body.session_id)
        if chat.project_id != (project.id if project else None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail={"code": "wrong_session",
                                        "message": "That conversation is about another video"})
        running = session.exec(select(AssistantTurn).where(
            AssistantTurn.session_id == chat.id,
            col(AssistantTurn.status).in_(ACTIVE_STATUSES))).first()
        if running is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail={"code": "turn_running",
                                        "message": "The assistant is still working on the last request"})
    else:
        ensure_user(session, user)
        chat = AssistantSession(id=str(uuid.uuid4()), user_id=user.id,
                                project_id=project.id if project else None)
        session.add(chat)
        session.commit()
        session.refresh(chat)

    if body.draft_spec is not None:
        base = body.draft_spec
    elif project is not None:
        base = project_service.decode(project.spec)
    else:
        base = dump_spec(starter_spec("Untitled video"))
    turn = worker.submit(session, chat, user_id=user.id, token=token, prompt=body.prompt.strip(),
                         base_spec=base,
                         base_version=body.base_version if body.base_version is not None
                         else (project.head_seq if project else None),
                         focus=body.focus)
    return DataResponse(data=_turn_read(turn))


@router.get("/turns", response_model=ListResponse[TurnRead])
def list_turns(user: CurrentUser, attention: bool = False,
               limit: int = Query(default=20, ge=1, le=100),
               session: Session = Depends(get_session)) -> ListResponse[TurnRead]:
    """With `attention`: what is running, or finished with a proposal not yet acted on."""
    query = select(AssistantTurn).where(AssistantTurn.user_id == user.id)
    if attention:
        query = query.where((col(AssistantTurn.status).in_(ACTIVE_STATUSES))
                            | (AssistantTurn.outcome == "pending"))
    rows = session.exec(query.order_by(AssistantTurn.created_at.desc()).limit(limit)).all()
    return ListResponse(data=[_turn_read(t) for t in rows], total=len(rows), limit=limit, offset=0)


@router.get("/turns/{turn_id}", response_model=DataResponse[TurnRead])
def get_turn(turn_id: str, user: CurrentUser,
             session: Session = Depends(get_session)) -> DataResponse[TurnRead]:
    return DataResponse(data=_turn_read(_owned_turn(session, user, turn_id)))


@router.delete("/turns/{turn_id}", response_model=DataResponse[TurnRead])
def stop_turn(turn_id: str, user: CurrentUser,
              session: Session = Depends(get_session)) -> DataResponse[TurnRead]:
    turn = _owned_turn(session, user, turn_id)
    if turn.status in ACTIVE_STATUSES:
        worker.queue.cancel(turn.id)
        if turn.status == "queued":
            # Never picked up, so nothing will unwind it: say so now.
            turn.status, turn.stage, turn.updated_at = "cancelled", "", utcnow()
            chat = session.get(AssistantSession, turn.session_id)
            if chat:
                worker.append_message(chat, "assistant", "_Stopped._", turn.id)
                session.add(chat)
            session.add(turn)
            session.commit()
            session.refresh(turn)
    return DataResponse(data=_turn_read(turn))


def _decide(session: Session, user, turn_id: str, outcome: str) -> AssistantTurn:
    turn = _owned_turn(session, user, turn_id)
    if turn.outcome != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "nothing_pending",
                                    "message": "That proposal was already applied or discarded"})
    turn.outcome, turn.updated_at = outcome, utcnow()
    session.add(turn)
    session.commit()
    session.refresh(turn)
    return turn


@router.post("/turns/{turn_id}/applied", response_model=DataResponse[TurnRead])
def mark_applied(turn_id: str, user: CurrentUser,
                 session: Session = Depends(get_session)) -> DataResponse[TurnRead]:
    """The editor loaded the proposal into its draft (saving it is the editor's)."""
    return DataResponse(data=_turn_read(_decide(session, user, turn_id, "applied")))


@router.post("/turns/{turn_id}/discarded", response_model=DataResponse[TurnRead])
def mark_discarded(turn_id: str, user: CurrentUser,
                   session: Session = Depends(get_session)) -> DataResponse[TurnRead]:
    return DataResponse(data=_turn_read(_decide(session, user, turn_id, "discarded")))


@router.post("/turns/{turn_id}/new-project", response_model=DataResponse[NewProjectRead],
             status_code=status.HTTP_201_CREATED)
def apply_as_new_project(turn_id: str, user: CurrentUser,
                         session: Session = Depends(get_session)) -> DataResponse[NewProjectRead]:
    """Apply a draft made from the project list: it becomes a project of its own, and the
    conversation moves with it."""
    turn = _owned_turn(session, user, turn_id)
    if turn.outcome != "pending" or not turn.proposed_spec:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "nothing_pending",
                                    "message": "That draft was already applied or discarded"})
    if turn.project_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"code": "has_project",
                                    "message": "This proposal is for an existing project"})
    spec, issues = parse_spec(json.loads(turn.proposed_spec))
    if spec is None:
        raise project_service.invalid_spec(issues)
    if spec.source is None:
        # Where it came from (S2), so a draft can be traced and redone.
        provider = active_provider(session, user.id)
        spec.source = BriefSource(kind="brief", prompt=turn.prompt,
                                  drafted_at=turn.created_at.isoformat(timespec="seconds") + "Z",
                                  provider=provider.provider_type if provider else None,
                                  model=provider.model if provider else None)
    project = project_service.create(session, user, spec, origin="brief",
                                     message="Drafted by the assistant", author="ai")
    turn.outcome, turn.project_id, turn.updated_at = "applied", project.id, utcnow()
    # Pictures the draft started generating belong to the new project now, so opening it
    # finds them and fills them in.
    from app.models.generation import Generation

    for row in session.exec(select(Generation).where(Generation.turn_id == turn.id)).all():
        row.project_id = project.id
        session.add(row)
    chat = session.get(AssistantSession, turn.session_id)
    if chat is not None:
        chat.project_id = project.id
        session.add(chat)
        # The conversation's other turns move with it, so the project shows them.
        for other in session.exec(select(AssistantTurn).where(
                AssistantTurn.session_id == chat.id)).all():
            other.project_id = project.id
            session.add(other)
    session.add(turn)
    session.commit()
    return DataResponse(data=NewProjectRead(project_id=project.id))
