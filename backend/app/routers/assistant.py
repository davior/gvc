"""The assistant: start a turn, follow it, stop it, and act on what it proposes.

A turn is a background job, so none of this needs the page that started it to stay
open. `GET /turns?attention=1` is what the header asks to say "something is running, or
waiting for you", on any page.
"""

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlmodel import Session, col, select

from app import web_fetch
from app.assistant import attachments as attach
from app.assistant import worker
from app.auth import CallerToken, CurrentUser
from app.clock import utcnow
from app.config import settings
from app.database import get_session
from app.jobs.runner import ACTIVE_STATUSES
from app.models.assistant import AssistantSession, AssistantTurn
from app.notes.client import NotesClient, NotesError
from app.providers import active_provider
from app.schemas import DataResponse, ListResponse
from app.schemas_assistant import (
    AttachmentRead, Message, NewProjectRead, NoteAttach, NoteChoice, SessionCreate,
    SessionRead, SessionSummary, Step, TurnCreate, TurnRead, UrlAttach,
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


def _attachment_read(item: dict) -> AttachmentRead:
    return AttachmentRead(id=item["id"], kind=item["kind"], title=item["title"],
                          source=item["source"], chars=item.get("chars", 0),
                          truncated=bool(item.get("truncated")),
                          preview=(item.get("text") or "")[:280],
                          added_at=item.get("added_at"))


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


def _session_read(session: Session, row: AssistantSession) -> SessionRead:
    turns = session.exec(select(AssistantTurn).where(AssistantTurn.session_id == row.id)
                         .order_by(AssistantTurn.created_at)).all()
    return SessionRead(
        **_summary(row).model_dump(),
        messages=[Message(**m) for m in json.loads(row.messages or "[]")],
        attachments=[_attachment_read(a) for a in json.loads(row.attachments or "[]")],
        turns=[_turn_read(t) for t in turns],
        cost=round(sum(t.cost or 0.0 for t in turns), 6),
    )


@router.post("/sessions", response_model=DataResponse[SessionRead],
             status_code=status.HTTP_201_CREATED)
def create_chat(body: SessionCreate, user: CurrentUser,
                session: Session = Depends(get_session)) -> DataResponse[SessionRead]:
    """An empty conversation, for material to be attached to before the first request.
    Asking without one (`POST /turns` with no session) still makes one as it goes."""
    if body.project_id:
        project_service.get_owned(session, user, body.project_id)
    ensure_user(session, user)
    row = AssistantSession(id=str(uuid.uuid4()), user_id=user.id, project_id=body.project_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    return DataResponse(data=_session_read(session, row))


@router.get("/sessions/{session_id}", response_model=DataResponse[SessionRead])
def get_chat(session_id: str, user: CurrentUser,
             session: Session = Depends(get_session)) -> DataResponse[SessionRead]:
    return DataResponse(data=_session_read(session, _owned_session(session, user, session_id)))


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


# ── attachments ───────────────────────────────────────────────────────────────
#
# Material to work from, turned into text as it is attached and kept on the
# conversation; see assistant/attachments.py for why it is a copy. Attaching while a
# turn runs is allowed: that turn has already read its prompt, and the next one sees it.

def _refused(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _attach(session: Session, row: AssistantSession, item: dict) -> AttachmentRead:
    existing = json.loads(row.attachments or "[]")
    try:
        attach.admit(existing, item)
    except attach.Unreadable as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from exc
    existing.append(item)
    row.attachments = json.dumps(existing, ensure_ascii=False)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return _attachment_read(item)


@router.post("/sessions/{session_id}/attachments/file", response_model=DataResponse[AttachmentRead],
             status_code=status.HTTP_201_CREATED)
def attach_file(session_id: str, user: CurrentUser, file: UploadFile = File(...),
                session: Session = Depends(get_session)) -> DataResponse[AttachmentRead]:
    row = _owned_session(session, user, session_id)
    limit = settings.assistant_attachment_max_mb * 1024 * 1024
    # One byte past the cap is enough to know it's over, without reading the rest.
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise _refused("too_large", f"Attach a file under {settings.assistant_attachment_max_mb} MB",
                       status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    name = (file.filename or "file").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    try:
        item = attach.make("file", name, name, attach.file_text(name, data, file.content_type or ""))
    except attach.Unreadable as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from exc
    return DataResponse(data=_attach(session, row, item))


@router.post("/sessions/{session_id}/attachments/note", response_model=DataResponse[AttachmentRead],
             status_code=status.HTTP_201_CREATED)
def attach_note(session_id: str, body: NoteAttach, user: CurrentUser, token: CallerToken,
                session: Session = Depends(get_session)) -> DataResponse[AttachmentRead]:
    row = _owned_session(session, user, session_id)
    try:
        with NotesClient(token) as notes:
            note = notes.get(body.note_id)
        item = attach.from_note(note.id, note.title, note.content)
    except NotesError as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from exc
    except attach.Unreadable as exc:
        raise _refused(exc.code, "That note is empty" if exc.code == "no_text" else exc.message,
                       exc.status_code) from exc
    return DataResponse(data=_attach(session, row, item))


@router.post("/sessions/{session_id}/attachments/url", response_model=DataResponse[AttachmentRead],
             status_code=status.HTTP_201_CREATED)
def attach_url(session_id: str, body: UrlAttach, user: CurrentUser,
               session: Session = Depends(get_session)) -> DataResponse[AttachmentRead]:
    row = _owned_session(session, user, session_id)
    url = body.url.strip()
    if "://" not in url:
        url = "https://" + url
    try:
        page = web_fetch.fetch(url, max_bytes=settings.assistant_attachment_max_mb * 1024 * 1024,
                               accept=attach.URL_TYPES)
        title, text = attach.url_text(page.content_type, page.charset, page.body)
        item = attach.make("url", title or page.url, page.url, text)
    except web_fetch.FetchError as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from exc
    except attach.Unreadable as exc:
        raise _refused(exc.code, "That page has no text to read" if exc.code == "no_text"
                       else exc.message, exc.status_code) from exc
    return DataResponse(data=_attach(session, row, item))


@router.delete("/sessions/{session_id}/attachments/{attachment_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def detach(session_id: str, attachment_id: str, user: CurrentUser,
           session: Session = Depends(get_session)) -> Response:
    row = _owned_session(session, user, session_id)
    existing = json.loads(row.attachments or "[]")
    kept = [a for a in existing if a.get("id") != attachment_id]
    if len(kept) == len(existing):
        raise _not_found("Attachment")
    row.attachments = json.dumps(kept, ensure_ascii=False)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notes", response_model=ListResponse[NoteChoice])
def find_notes(user: CurrentUser, token: CallerToken, q: str = "",
               limit: int = Query(default=20, ge=1, le=50)) -> ListResponse[NoteChoice]:
    """The user's notes in Gecko Notes, to pick one to attach."""
    try:
        with NotesClient(token) as notes:
            found = notes.search(q, limit=limit)
    except NotesError as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from exc
    return ListResponse(data=[NoteChoice(id=n.id, title=n.title, preview=n.preview,
                                         modified_at=n.modified_at) for n in found],
                        total=len(found), limit=limit, offset=0)


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
