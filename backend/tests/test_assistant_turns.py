"""Whole assistant turns, over HTTP and through the worker, with a scripted provider.

A turn is a background job: these start one with the API, run it with `worker._run` (the
queue is stubbed in conftest, so nothing runs on its own), then read what it left on its
row, which is what a person coming back to the page would see.
"""

import json

import pytest

from app.assistant import worker
from app.models.provider import AIProvider
from app.models.usage import UsageEvent
from tests.conftest import TEST_USER_ID
from tests.fake_provider import ScriptedProvider, call, says
from tests.fake_siblings import gam_asset, hit, transcript


@pytest.fixture
def engine_for_worker(engine, monkeypatch):
    monkeypatch.setattr(worker.queue, "engine", engine)
    return engine


@pytest.fixture
def provider(session, monkeypatch):
    """An active provider row (the API checks one exists) and a script to play back."""
    from app.services.users import ensure_user
    from app.auth import UserCtx

    ensure_user(session, UserCtx(id=TEST_USER_ID, username=TEST_USER_ID))
    session.add(AIProvider(user_id=TEST_USER_ID, name="Claude", provider_type="anthropic",
                           model="claude-opus-5-5", api_key="sk", is_active=True))
    session.commit()
    scripted = ScriptedProvider(script=[])
    monkeypatch.setattr(worker, "build_provider", lambda session, user_id: scripted)
    return scripted


@pytest.fixture
def library(siblings):
    reel = gam_asset("r", "River interview", "video", duration_seconds=600.0)
    picture = gam_asset("p", "Valley map", "image", width=1600, height=900)
    siblings.assets.update({"r": reel, "p": picture})
    siblings.hits = [hit(reel, start=42.0, end=47.5, snippet="the «water» is gone"),
                     hit(picture)]
    return siblings


DRAFT = {
    "title": "Water Wars",
    "style": {"transition": {"style": "fade", "duration": 0.6}},
    "assets": {"a_map": {"from": "gam", "id": "p", "type": "image"}},
    "segments": [
        {"id": "s_title", "kind": "card", "label": "Title",
         "card": {"variant": "title", "title": "Water Wars"}},
        {"id": "s_valley", "kind": "scene", "label": "The valley",
         "visual": {"asset": "a_map", "motion": {"effect": "zoom_in"}},
         # The mistake the model then fixes from the issues it is handed.
         "transition_in": {"style": "sideways"},
         "narration": {"beats": [{"id": "b1", "text": "The valley used to run clear."}]}},
    ],
}


def start(client, **body):
    res = client.post("/api/assistant/turns", json={"prompt": "Make it", **body})
    assert res.status_code == 202, res.text
    return res.json()["data"]


def test_a_video_from_a_prompt_searches_drafts_repairs_and_becomes_a_project(
        auth_client, session, provider, library, engine_for_worker):
    provider.script += [
        says("Looking in your library.", call("search_assets", query="water", type="video")),
        says("", call("replace_spec", spec=DRAFT)),
        says("", call("update_segment", segment_id="s_valley",
                      changes={"transition_in": {"style": "dissolve"}})),
        says("", call("set_visual", segment_id="s_valley", gam_id="r")),
        says("A two-scene draft: a title, then the valley over the river interview."),
    ]
    turn = start(auth_client, prompt="A short video about the water wars")
    assert turn["status"] == "queued" and turn["project_id"] is None

    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["status"] == "done", done
    assert done["reply"] == "A two-scene draft: a title, then the valley over the river interview."
    assert done["outcome"] == "pending"
    # The proposal is the repaired draft, the found moment cut in.
    valley = done["proposed_spec"]["segments"][1]
    assert valley["transition_in"] == {"style": "dissolve"}
    assert valley["visual"]["trim"] == {"in": 41.5, "out": 48.0}
    assert done["changes"][0].startswith("Drafted the video")
    kinds = [s["kind"] for s in done["steps"]]
    assert kinds[:2] == ["think", "search"] and "edit" in kinds
    # The model was told the issues, and fixed them in the next call.
    replace_result = provider.results()[1]
    assert "transition_in" in replace_result.content and "to fix" in replace_result.content
    # Told it is a new video, given the reference and the tools.
    assert "new video" in provider.started["system"][-1]
    assert "set_visual" in provider.started["tools"]

    # Spend: one row per call, the turn's total on the turn.
    rows = session.query(UsageEvent).all()
    assert len(rows) == 5 and all(r.turn_id == turn["id"] for r in rows)
    assert done["cost"] == pytest.approx(sum(r.cost for r in rows))

    # Applying it from the project list makes the project, with the chat moved over.
    made = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project")
    assert made.status_code == 201, made.text
    project_id = made.json()["data"]["project_id"]
    project = auth_client.get(f"/api/projects/{project_id}").json()["data"]
    assert project["origin"] == "brief" and project["title"] == "Water Wars"
    assert project["spec"]["source"]["kind"] == "brief"
    assert project["spec"]["source"]["prompt"] == "A short video about the water wars"
    versions = auth_client.get(f"/api/projects/{project_id}/versions").json()["data"]
    assert versions[0]["author"] == "ai"
    chats = auth_client.get("/api/assistant/sessions", params={"project_id": project_id}).json()
    assert [c["id"] for c in chats["data"]] == [turn["session_id"]]
    again = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project")
    assert again.status_code == 409


def project_with(client, spec):
    res = client.post("/api/projects", json={"spec": spec})
    assert res.status_code == 201, res.text
    return res.json()["data"]


VALID = json.loads(json.dumps(DRAFT))
VALID["segments"][1]["transition_in"] = {"style": "fade"}


def test_an_edit_is_proposed_on_the_draft_and_waits_to_be_applied(
        auth_client, provider, library, engine_for_worker):
    project = project_with(auth_client, VALID)
    # The editor's draft carries an unsaved edit; the proposal must keep it.
    draft = json.loads(json.dumps(project["spec"]))
    draft["segments"][1]["label"] = "Valley (unsaved)"
    provider.script += [
        says("", call("update_segment", segment_id="s_valley",
                      changes={"transition_in": {"style": "dissolve"}})),
        says("Dissolve into the valley now."),
    ]
    turn = start(auth_client, project_id=project["id"], prompt="dissolve into this scene",
                 draft_spec=draft, base_version=project["version"], focus="s_valley")
    worker._run(turn["id"])

    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    valley = done["proposed_spec"]["segments"][1]
    assert valley["transition_in"] == {"style": "dissolve"}
    assert valley["label"] == "Valley (unsaved)"
    assert done["base_version"] == project["version"]
    assert "Focused segment" in provider.started["system"][-1]
    # Nothing reached the project.
    saved = auth_client.get(f"/api/projects/{project['id']}").json()["data"]
    assert saved["version"] == project["version"]

    # Still waiting when the person comes back, on any page.
    waiting = auth_client.get("/api/assistant/turns", params={"attention": True}).json()["data"]
    assert [t["id"] for t in waiting] == [turn["id"]]
    assert auth_client.post(f"/api/assistant/turns/{turn['id']}/applied").status_code == 200
    assert auth_client.get("/api/assistant/turns", params={"attention": True}).json()["data"] == []
    assert auth_client.post(f"/api/assistant/turns/{turn['id']}/discarded").status_code == 409


def test_a_question_changes_nothing_and_proposes_nothing(
        auth_client, provider, engine_for_worker):
    project = project_with(auth_client, VALID)
    provider.script += [says("", call("estimate")), says("About 7 seconds.")]
    turn = start(auth_client, project_id=project["id"], prompt="how long is it?")
    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["reply"] == "About 7 seconds." and done["proposed_spec"] is None
    assert done["outcome"] == "" and done["changes"] == []


def test_a_model_that_stops_with_issues_is_told_to_fix_them_then_nothing_is_proposed(
        auth_client, provider, engine_for_worker):
    provider.script += [
        says("", call("replace_spec", spec=DRAFT)),
        says("Here it is."), says("Done, I think."), says("Really done."),
    ]
    turn = start(auth_client, prompt="draft")
    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    told = [entry for kind, entry in provider.log if kind == "told"]
    assert len(told) == 2 and "transition_in" in told[0]
    assert done["proposed_spec"] is None and "nothing to apply" in done["reply"]


def test_the_conversation_carries_on_with_its_history(auth_client, provider, engine_for_worker):
    project = project_with(auth_client, VALID)
    provider.script += [says("First answer.")]
    first = start(auth_client, project_id=project["id"], prompt="first question")
    worker._run(first["id"])
    provider.script += [says("Second answer.")]
    second = start(auth_client, project_id=project["id"], session_id=first["session_id"],
                   prompt="second question")
    worker._run(second["id"])
    assert provider.started["history"] == [("user", "first question"),
                                           ("assistant", "First answer.")]
    assert provider.started["prompt"] == "second question"
    chat = auth_client.get(f"/api/assistant/sessions/{first['session_id']}").json()["data"]
    assert [m["text"] for m in chat["messages"]] == [
        "first question", "First answer.", "second question", "Second answer."]
    assert [t["id"] for t in chat["turns"]] == [first["id"], second["id"]]
    assert chat["title"] == "first question"


def test_one_turn_at_a_time_per_conversation(auth_client, provider):
    first = start(auth_client)
    again = auth_client.post("/api/assistant/turns",
                             json={"prompt": "more", "session_id": first["session_id"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "turn_running"


def test_no_provider_says_where_to_set_one_up(auth_client):
    res = auth_client.post("/api/assistant/turns", json={"prompt": "hi"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_provider"


def test_stop_ends_a_queued_turn_and_a_running_one_at_its_next_round(
        auth_client, provider, engine_for_worker, monkeypatch):
    queued = start(auth_client)
    stopped = auth_client.delete(f"/api/assistant/turns/{queued['id']}").json()["data"]
    assert stopped["status"] == "cancelled"
    worker._run(queued["id"])   # reaching it later, the worker leaves it alone
    assert auth_client.get(f"/api/assistant/turns/{queued['id']}").json()["data"]["status"] == "cancelled"

    running = start(auth_client, prompt="again")
    provider.script += [says("", call("estimate"))]
    calls = iter([False, True, True])
    monkeypatch.setattr(worker.queue, "is_cancelled", lambda job_id: next(calls))
    worker._run(running["id"])
    done = auth_client.get(f"/api/assistant/turns/{running['id']}").json()["data"]
    assert done["status"] == "cancelled"


def test_a_restart_ends_a_turn_and_says_so(auth_client, provider, engine_for_worker):
    turn = start(auth_client)
    worker._tokens.clear()      # what a restart does to the in-memory tokens
    worker._run(turn["id"])
    ended = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert ended["status"] == "error" and "restart" in ended["error"]
    chat = auth_client.get(f"/api/assistant/sessions/{turn['session_id']}").json()["data"]
    assert "restart" in chat["messages"][-1]["text"]


def test_a_provider_failure_is_the_turns_error_in_its_own_words(
        auth_client, provider, engine_for_worker, monkeypatch):
    from app.providers.base import ProviderError

    def broken():
        raise ProviderError("Claude: the API key was rejected")

    turn = start(auth_client)
    provider.script.clear()
    monkeypatch.setattr(provider, "conversation", lambda **kw: type(
        "C", (), {"ask": staticmethod(broken)})())
    worker._run(turn["id"])
    failed = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert failed["status"] == "error" and "key was rejected" in failed["error"]


def test_the_token_is_never_stored(auth_client, session, provider, engine_for_worker):
    from app.models.assistant import AssistantTurn

    turn = start(auth_client)
    row = session.get(AssistantTurn, turn["id"])
    assert "token" not in json.dumps(row.model_dump(mode="json")).lower()


def test_someone_elses_conversation_and_turns_do_not_exist_for_you(
        auth_client, provider, switch_user):
    turn = start(auth_client)
    switch_user("someone-else")
    for method, url in (("get", f"/api/assistant/turns/{turn['id']}"),
                        ("delete", f"/api/assistant/turns/{turn['id']}"),
                        ("post", f"/api/assistant/turns/{turn['id']}/applied"),
                        ("post", f"/api/assistant/turns/{turn['id']}/new-project"),
                        ("get", f"/api/assistant/sessions/{turn['session_id']}"),
                        ("delete", f"/api/assistant/sessions/{turn['session_id']}")):
        assert getattr(auth_client, method)(url).status_code == 404, (method, url)


def test_deleting_a_project_deletes_its_conversations(auth_client, session, provider):
    from app.models.assistant import AssistantSession, AssistantTurn

    project = project_with(auth_client, VALID)
    start(auth_client, project_id=project["id"])
    assert auth_client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert session.query(AssistantTurn).count() == 0
    assert session.query(AssistantSession).count() == 0


def test_a_draft_generates_its_pictures_but_never_its_video(
        auth_client, session, provider, library, engine_for_worker):
    from sqlmodel import select

    from app.models.generation import Generation

    draft = json.loads(json.dumps(VALID))
    draft["segments"].append({"id": "s_flood", "kind": "scene", "label": "Flood",
                              "narration": {"beats": [{"id": "b1", "text": "Then it rose."}]}})
    provider.script += [
        says("", call("replace_spec", spec=draft)),
        says("", call("generate_image", prompt="An illustration of the dam, wide",
                      segment_id="s_title", use_as="overlay", label="Dam")),
        says("", call("add_placeholder", segment_id="s_flood", kind="generate",
                      media_type="video", text="Water rising over the valley floor")),
        says("The dam picture is generating; press Generate on the flood scene for its clip."),
    ]
    res = auth_client.post("/api/assistant/turns",
                           json={"prompt": "Water wars, with an illustration of the dam"},
                           headers={"Authorization": "Bearer user-token"})
    turn = res.json()["data"]
    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["status"] == "done", done
    # One job, for the picture, as the user, against the turn.
    [sent] = library.generations
    assert sent["prompt"] == "An illustration of the dam, wide"
    assert sent["authorization"] == "Bearer user-token"
    [row] = session.exec(select(Generation)).all()
    assert (row.turn_id, row.project_id, row.asset_key) == (turn["id"], None, "a_dam")
    assets = done["proposed_spec"]["assets"]
    flood = done["proposed_spec"]["segments"][2]["visual"]["asset"]
    assert assets[flood]["type"] == "video" and assets[flood]["from"] == "generate"
    assert any("Generating a picture" in c for c in done["changes"])

    made = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project").json()["data"]
    listed = auth_client.get(f"/api/projects/{made['project_id']}/generations").json()["data"]
    assert [g["asset_key"] for g in listed] == ["a_dam"]


def test_clips_are_picked_in_a_pass_of_their_own_paid_for_on_the_turn(
        auth_client, session, provider, library, engine_for_worker):
    project = project_with(auth_client, VALID)
    library.transcripts["r"] = transcript(
        "r", (30.0, 36.0, "We came here in the spring."),
        (36.5, 47.5, "Back then the river ran clear all year, but now the water is gone."))
    provider.script += [
        says("", call("search_assets", query="water", type="video")),
        says("", call("find_clips", gam_id="r", idea="The river is gone")),
        # The picking pass: its own conversation, answered from the same script.
        says('[{"first": 1, "last": 1, "score": 9, "why": "Says it plainly."}]'),
        says("", call("set_visual", segment_id="s_valley", gam_id="r",
                      trim={"in": 36.0, "out": 48.0})),
        says("The valley now cuts to the river interview saying the water is gone."),
    ]
    turn = start(auth_client, prompt="Find a better clip for the valley",
                 project_id=project["id"])
    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["status"] == "done", done

    picked = provider.results()[1]
    assert '"trim":{"in":36.0,"out":48.0}' in picked.content and "Says it plainly" in picked.content
    # The pass was a conversation of its own, the last one started: no tools, no history,
    # the picker's instructions and the numbered transcript.
    assert provider.started["tools"] == [] and provider.started["history"] == []
    assert "You pick clips" in provider.started["system"][0]
    assert "1 [36.5-47.5] Back then" in provider.started["prompt"]
    assert any(s["text"] == "Picking clips from River interview" for s in done["steps"])
    assert done["proposed_spec"]["segments"][1]["visual"]["trim"] == {"in": 36.0, "out": 48.0}
    # Five model calls, the pass among them, all on the turn's bill.
    rows = session.query(UsageEvent).all()
    assert len(rows) == 5 and all(r.turn_id == turn["id"] for r in rows)
