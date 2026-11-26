"""Request and response bodies for the assistant."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas_recipes import MAX_INPUT_CHARS, RecipeDefaults


class TurnCreate(BaseModel):
    # None: continue in a new session (for this project, or for a new video).
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    # What to ask. With `recipe_id` it may be empty: the recipe's prompt, filled in, is
    # what is asked, and the server fills it in so every client asks the same thing.
    prompt: str = Field(default="", max_length=20_000)
    # The editor's draft, unsaved edits included. Absent: the saved version (or, with
    # no project, a blank starter).
    draft_spec: Optional[Dict[str, Any]] = None
    # The project version the draft was opened from.
    base_version: Optional[int] = None
    # The segment open in the editor, if any.
    focus: Optional[str] = None
    # One of the suite's personas (`GET /assistant/personas`), or none. The suite is the
    # authority on whether it exists: an unknown one ends the turn with the suite's sentence.
    persona_id: Optional[str] = Field(default=None, max_length=64)
    # Carry the whole request out in one turn, with the larger budget of pictures and
    # rounds, instead of stopping at the everyday limit for the person to say "continue".
    auto_run: bool = False
    # Run one of the user's recipes, with these values for its inputs (names match
    # loosely). `date` and `time` may come in here too, from the asker's own clock.
    recipe_id: Optional[str] = Field(default=None, max_length=64)
    recipe_inputs: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _something_to_ask(self) -> "TurnCreate":
        if not self.recipe_id and not self.prompt.strip():
            raise ValueError("Say what to do, or run a recipe")
        if len(self.recipe_inputs) > 50 or any(
                len(k) > 100 or len(v) > MAX_INPUT_CHARS for k, v in self.recipe_inputs.items()):
            raise ValueError(f"A recipe input is at most {MAX_INPUT_CHARS} characters")
        return self


class PersonaRead(BaseModel):
    """What a picker shows of one of the suite's personas: never its system prompt."""

    id: str
    name: str
    description: str = ""
    avatar: Optional[str] = None


class Step(BaseModel):
    kind: str
    text: str


class NoteProposalRead(BaseModel):
    """A note the assistant proposed for Gecko Notes, decided apart from the video."""

    note_ref: str
    title: str
    markdown: str
    folder: Optional[str] = None
    state: str = "pending"          # pending | created | discarded
    note_url: Optional[str] = None  # once created: the note's page in Gecko Notes


class PlaylistItemProposal(BaseModel):
    """An item the assistant proposed adding to a GAM playlist."""

    asset_id: str
    name: str = ""
    type: str = ""
    in_point: Optional[float] = None
    out_point: Optional[float] = None
    image_seconds: Optional[float] = None
    label: Optional[str] = None
    note: Optional[str] = None


class PlaylistRemovalProposal(BaseModel):
    item_id: str
    name: str = ""
    label: Optional[str] = None


class PlaylistProposalRead(BaseModel):
    """A change to one of the user's GAM playlists, or a new one, made only by its button."""

    playlist_ref: str
    playlist_id: Optional[str] = None   # None for a new playlist until it is made
    name: str
    description: Optional[str] = None
    add: List[PlaylistItemProposal] = []
    remove: List[PlaylistRemovalProposal] = []
    state: str = "pending"              # pending | applied | discarded
    # Once applied: what could not be done (an item already gone), one sentence each.
    skipped: List[str] = []
    playlist_url: Optional[str] = None  # once applied: the playlist's page in GAM


class RecipeDraft(BaseModel):
    """A recipe as a proposal shows it: the whole of it, before or after."""

    name: str = ""
    prompt: str = ""
    tags: List[str] = []
    defaults: RecipeDefaults = Field(default_factory=RecipeDefaults)
    inputs: List[str] = []


class RecipeProposalRead(BaseModel):
    """A change to the user's recipe list the assistant proposed, saved only by its button."""

    recipe_ref: str
    op: str                          # create | update | delete
    recipe_id: Optional[str] = None  # the recipe changed; for a create, once saved
    before: Optional[RecipeDraft] = None   # update and delete: as it was when proposed
    after: Optional[RecipeDraft] = None    # create and update: as it will be
    fields: List[str] = []           # update: which fields change
    state: str = "pending"           # pending | saved | discarded


class TurnRead(BaseModel):
    id: str
    session_id: str
    project_id: Optional[str] = None
    status: str
    stage: str
    detail: str
    error: Optional[str] = None
    prompt: str
    steps: List[Step] = []
    reply: str = ""
    # Present while there is a proposal: the whole spec to load into the editor.
    proposed_spec: Optional[Dict[str, Any]] = None
    changes: List[str] = []
    outcome: str = ""
    notes: List[NoteProposalRead] = []
    recipes: List[RecipeProposalRead] = []
    playlists: List[PlaylistProposalRead] = []
    # The recipe this turn ran, if any, and its name as it is now (None once deleted).
    recipe_id: Optional[str] = None
    recipe_name: Optional[str] = None
    base_version: Optional[int] = None
    persona_id: Optional[str] = None
    auto_run: bool = False
    cost: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    role: str
    text: str
    turn_id: Optional[str] = None
    at: Optional[str] = None


class SessionSummary(BaseModel):
    id: str
    project_id: Optional[str] = None
    title: str
    created_at: datetime
    updated_at: datetime


class AttachmentRead(BaseModel):
    """An attachment as listed: what it is and how much of it, not its whole text."""

    id: str
    kind: str
    title: str
    source: str
    chars: int
    truncated: bool = False
    # The start of the text, so a person can see what was read.
    preview: str = ""
    # Images only: a small data URL to show, and the size the model is sent.
    thumb: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    added_at: Optional[str] = None


class SessionCreate(BaseModel):
    # None: a conversation about a video not yet made (from the project list).
    project_id: Optional[str] = None


class NoteAttach(BaseModel):
    note_id: str = Field(min_length=1, max_length=200)


class UrlAttach(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class NoteChoice(BaseModel):
    id: str
    title: str
    preview: str = ""
    modified_at: Optional[str] = None


class SessionRead(SessionSummary):
    messages: List[Message] = []
    attachments: List[AttachmentRead] = []
    # Every turn of the session, newest last, so the panel can show each one's steps,
    # change card and cost beside its message.
    turns: List[TurnRead] = []
    cost: float = 0.0


class NewProjectRead(BaseModel):
    project_id: str
