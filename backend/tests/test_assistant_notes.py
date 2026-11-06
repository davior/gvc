"""The assistant proposing a note for Gecko Notes, made only when its button is pressed.

A note is not part of the video, so it is decided apart from the spec proposal: a turn can
propose a note, an edit or both. Created with the token of whoever presses the button (the
turn's own is gone by then), through Notes' `POST /api/notes/from-markdown`.
"""

import pytest

from app.assistant import tools as T
from app.assistant import worker
from app.assistant.tools import Working
from app.config import settings
from app.providers.base import ToolCall
from tests.fake_provider import call, says
from tests.fake_siblings import GAM
from tests.test_assistant_turns import engine_for_worker, provider, start  # noqa: F401 - fixtures

TOKEN = {"Authorization": "Bearer user-token"}


def run(w, name, **args):
    return T.execute(w, ToolCall(id="c1", name=name, arguments=args))


def test_the_tool_is_offered_only_with_a_token_to_make_the_note_with():
    names = lambda w: {s.name for s in T.specs_for(w)}  # noqa: E731
    assert "propose_note" not in names(Working({"title": "x"}))
    assert "propose_note" in names(Working({"title": "x"}, can_note=True))


def test_a_note_is_recorded_apart_from_the_video_and_a_second_with_its_title_rewrites_it():
    w = Working({"title": "x"}, can_note=True)
    first = run(w, "propose_note", title="Shot list", markdown="- one")
    run(w, "propose_note", title="shot list", markdown="- one\n- two", folder="Shoots")
    assert not first.is_error and w.changes == []
    (note,) = w.notes
    assert (note["markdown"], note["folder"], note["state"]) == ("- one\n- two", "Shoots", "pending")
    assert run(w, "propose_note", title="", markdown="x").is_error


def ask_for_a_note(auth_client, provider):
    provider.script += [
        says("", call("propose_note", title="River research",
                      markdown="# River\n\n- [Interview](/a/r): the water is gone.")),
        says("A note for Gecko Notes, ready to create."),
    ]
    turn = start(auth_client, prompt="Put my research on the river in Gecko Notes")
    worker._run(turn["id"])
    return auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]


def test_a_proposed_note_is_created_in_notes_by_its_button_once(
        auth_client, provider, siblings, engine_for_worker, monkeypatch):
    # The turn holds a token while it runs, as it does when started by a signed-in user.
    real_submit = worker.submit
    monkeypatch.setattr(worker, "submit", lambda *a, **k: real_submit(*a, **{**k, "token": "turn-token"}))
    done = ask_for_a_note(auth_client, provider)
    (note,) = done["notes"]
    # Not the video: no spec proposal, nothing to apply in the editor.
    assert done["proposed_spec"] is None and done["outcome"] == ""
    assert note["state"] == "pending" and siblings.created_notes == []

    made = auth_client.post(f"/api/assistant/turns/{done['id']}/notes/{note['note_ref']}/create",
                            headers=TOKEN)
    assert made.status_code == 200, made.text
    (after,) = made.json()["data"]["notes"]
    assert after["state"] == "created"
    assert after["note_url"] == f"{settings.notes_base_url.rstrip('/')}/notes/note-1"
    (sent,) = siblings.created_notes
    assert sent["authorization"] == "Bearer user-token" and sent["source_app"] == "gvc"
    assert f"[Interview]({GAM}/a/r)" in sent["markdown"]

    again = auth_client.post(f"/api/assistant/turns/{done['id']}/notes/{note['note_ref']}/create",
                             headers=TOKEN)
    assert again.status_code == 409 and len(siblings.created_notes) == 1


def test_a_note_can_be_discarded_and_an_older_notes_says_so(
        auth_client, provider, siblings, engine_for_worker, monkeypatch):
    real_submit = worker.submit
    monkeypatch.setattr(worker, "submit", lambda *a, **k: real_submit(*a, **{**k, "token": "t"}))
    done = ask_for_a_note(auth_client, provider)
    ref = done["notes"][0]["note_ref"]

    siblings.create_note_status = 404
    old = auth_client.post(f"/api/assistant/turns/{done['id']}/notes/{ref}/create", headers=TOKEN)
    assert old.status_code == 409 and old.json()["detail"]["code"] == "notes_outdated"
    # Still pending, so it can be pressed again once Notes is updated, or thrown away.
    gone = auth_client.post(f"/api/assistant/turns/{done['id']}/notes/{ref}/discard")
    assert gone.json()["data"]["notes"][0]["state"] == "discarded"
    missing = auth_client.post(f"/api/assistant/turns/{done['id']}/notes/nope/discard")
    assert missing.status_code == 404


def test_without_a_token_no_note_is_offered(auth_client, provider, engine_for_worker):
    provider.script += [says("I can't write to Gecko Notes from here.")]
    turn = start(auth_client, prompt="Put this in Gecko Notes")
    worker._run(turn["id"])
    offered = set(provider.started["tools"])
    assert "propose_note" not in offered


@pytest.fixture(autouse=True)
def _siblings(siblings):
    return siblings
