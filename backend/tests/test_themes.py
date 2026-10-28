"""Themes: the list, the default a new project starts with, what they add to a
generation's prompt, and the assistant choosing one."""

import json

import pytest

from app.assistant import tools as T
from app.assistant import worker
from app.assistant.prompt import context
from app.assistant.tools import Working
from app.models.provider import AIProvider
from app.providers.base import ToolCall
from tests.conftest import TEST_USER_ID
from tests.fake_provider import ScriptedProvider, call, says

NOIR = {"name": "Noir", "prompt": "Black and white, hard shadows, 1940s film grain."}
CLAY = {"name": "Claymation", "prompt": "Stop-motion clay figures, soft studio light."}


def make(client, **body) -> dict:
    res = client.post("/api/themes", json=body)
    assert res.status_code == 201, res.text
    return res.json()["data"]


# ── the list ─────────────────────────────────────────────────────────────────

def test_themes_are_listed_by_name_and_edited_in_place(auth_client):
    noir = make(auth_client, **NOIR)
    make(auth_client, **CLAY)
    listed = auth_client.get("/api/themes").json()
    assert [t["name"] for t in listed["data"]] == ["Claymation", "Noir"]
    assert listed["total"] == 2

    res = auth_client.put(f"/api/themes/{noir['id']}", json={"prompt": "  Sepia, grainy.  "})
    assert res.status_code == 200
    assert res.json()["data"] | {"updated_at": None} == noir | {
        "prompt": "Sepia, grainy.", "updated_at": None}

    assert auth_client.delete(f"/api/themes/{noir['id']}").status_code == 204
    assert [t["name"] for t in auth_client.get("/api/themes").json()["data"]] == ["Claymation"]


def test_there_is_at_most_one_default(auth_client):
    noir = make(auth_client, **NOIR, is_default=True)
    make(auth_client, **CLAY, is_default=True)
    defaults = {t["name"] for t in auth_client.get("/api/themes").json()["data"]
                if t["is_default"]}
    assert defaults == {"Claymation"}

    auth_client.put(f"/api/themes/{noir['id']}", json={"is_default": True})
    defaults = {t["name"] for t in auth_client.get("/api/themes").json()["data"]
                if t["is_default"]}
    assert defaults == {"Noir"}
    # And none at all is allowed.
    auth_client.put(f"/api/themes/{noir['id']}", json={"is_default": False})
    assert not any(t["is_default"] for t in auth_client.get("/api/themes").json()["data"])


def test_a_theme_needs_a_name_and_a_modifier_of_reasonable_length(auth_client):
    assert auth_client.post("/api/themes", json={"name": ""}).status_code == 422
    assert auth_client.post("/api/themes", json={"name": "Long", "prompt": "x" * 1501}
                            ).status_code == 422


def test_someone_elses_themes_do_not_exist_for_you(auth_client, switch_user):
    noir = make(auth_client, **NOIR)
    switch_user("someone-else")
    assert auth_client.get("/api/themes").json()["data"] == []
    assert auth_client.put(f"/api/themes/{noir['id']}", json={"name": "Mine"}
                           ).status_code == 404
    assert auth_client.delete(f"/api/themes/{noir['id']}").status_code == 404


# ── a new project's theme ────────────────────────────────────────────────────

def test_a_new_project_starts_with_the_default_theme(auth_client):
    blank = auth_client.post("/api/projects", json={"title": "Plain"}).json()["data"]
    assert "theme" not in blank["spec"]["style"]

    noir = make(auth_client, **NOIR, is_default=True)
    blank = auth_client.post("/api/projects", json={"title": "Moody"}).json()["data"]
    assert blank["spec"]["style"]["theme"] == noir["id"]
    pushed = auth_client.post("/api/projects/import", json={"spec": {"title": "From a note"}})
    assert pushed.json()["data"]["spec"]["style"]["theme"] == noir["id"]


def test_a_pasted_spec_keeps_its_own_theme_but_not_someone_elses(auth_client):
    make(auth_client, **NOIR, is_default=True)
    clay = make(auth_client, **CLAY)
    mine = auth_client.post("/api/projects", json={
        "spec": {"title": "Clay", "style": {"theme": clay["id"]}}}).json()["data"]
    assert mine["spec"]["style"]["theme"] == clay["id"]

    foreign = auth_client.post("/api/projects", json={
        "spec": {"title": "Stranger", "style": {"theme": "not-one-of-yours"}}}).json()["data"]
    assert foreign["spec"]["style"]["theme"] != "not-one-of-yours"


def test_the_theme_is_saved_with_the_spec(auth_client):
    clay = make(auth_client, **CLAY)
    project = auth_client.post("/api/projects", json={"title": "Clay"}).json()["data"]
    spec = project["spec"]
    spec["style"]["theme"] = clay["id"]
    saved = auth_client.put(f"/api/projects/{project['id']}", json={"spec": spec})
    assert saved.json()["data"]["spec"]["style"]["theme"] == clay["id"]


# ── what a theme does to a generation ────────────────────────────────────────

SPEC = {
    "title": "Water Wars",
    "assets": {
        "a_dam": {"from": "generate", "type": "image", "prompt": "A dam at dusk"},
        "a_flood": {"from": "generate", "type": "video", "prompt": "Water rising"},
    },
    "segments": [
        {"id": "s_dam", "kind": "scene", "visual": {"asset": "a_dam"}},
        {"id": "s_flood", "kind": "scene", "visual": {"asset": "a_flood"}},
    ],
}


def generate(client, project_id, **body):
    return client.post(f"/api/projects/{project_id}/generations", json=body,
                       headers={"Authorization": "Bearer user-token"})


def themed_project(client, theme_id):
    spec = json.loads(json.dumps(SPEC))
    spec["style"] = {"theme": theme_id}
    return client.post("/api/projects", json={"spec": spec}).json()["data"]


def test_the_projects_theme_is_added_to_what_is_sent_but_not_to_the_row(
        auth_client, siblings):
    noir = make(auth_client, **NOIR)
    project = themed_project(auth_client, noir["id"])
    res = generate(auth_client, project["id"], asset_key="a_dam")
    assert res.status_code == 202, res.text
    [sent] = siblings.generations
    assert sent["prompt"] == "A dam at dusk\n\n" + NOIR["prompt"]
    # The row and the placeholder keep the prompt as written, so trying again doesn't
    # add the theme twice.
    assert res.json()["data"]["prompt"] == "A dam at dusk"


def test_an_unsaved_theme_change_in_the_draft_is_what_counts(auth_client, siblings):
    noir = make(auth_client, **NOIR)
    clay = make(auth_client, **CLAY)
    project = themed_project(auth_client, noir["id"])
    draft = {**project["spec"], "style": {**project["spec"]["style"], "theme": clay["id"]}}
    generate(auth_client, project["id"], asset_key="a_dam", draft_spec=draft)
    assert siblings.generations[0]["prompt"].endswith(CLAY["prompt"])


def test_a_clip_from_a_prompt_styles_both_its_picture_and_its_motion(
        auth_client, siblings):
    noir = make(auth_client, **NOIR)
    project = themed_project(auth_client, noir["id"])
    res = generate(auth_client, project["id"], asset_key="a_flood", make_picture=True,
                   picture_prompt="A valley floor")
    assert res.status_code == 202, res.text
    assert siblings.generations[0]["prompt"] == "A valley floor\n\n" + NOIR["prompt"]
    siblings.gen_jobs["job-1"].update(status="done", progress=100, result_asset_id="pic",
                                      result_asset_ids=["pic"])
    auth_client.get(f"/api/projects/{project['id']}/generations")
    assert siblings.generations[1]["prompt"] == "Water rising\n\n" + NOIR["prompt"]


def test_a_deleted_theme_styles_nothing(auth_client, siblings):
    noir = make(auth_client, **NOIR)
    project = themed_project(auth_client, noir["id"])
    auth_client.delete(f"/api/themes/{noir['id']}")
    assert generate(auth_client, project["id"], asset_key="a_dam").status_code == 202
    assert siblings.generations[0]["prompt"] == "A dam at dusk"


def test_a_prompt_too_long_with_its_theme_is_refused_before_gam(auth_client, siblings):
    wordy = make(auth_client, name="Wordy", prompt="w" * 1500)
    project = themed_project(auth_client, wordy["id"])
    res = generate(auth_client, project["id"], asset_key="a_dam", prompt="p" * 3000)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "prompt_too_long"
    assert "Wordy" in res.json()["detail"]["message"]
    assert siblings.generations == []


# ── the assistant ────────────────────────────────────────────────────────────

THEMES = {"t-noir": NOIR, "t-clay": CLAY}


def tool(w, name, **arguments):
    return T.execute(w, ToolCall(id="x", name=name, arguments=arguments))


def test_set_theme_takes_a_name_or_id_and_refuses_one_that_isnt_listed():
    w = Working({"title": "T"}, themes=THEMES)
    assert not tool(w, "set_theme", theme="claymation").is_error
    assert w.data["style"]["theme"] == "t-clay"
    assert not tool(w, "set_theme", theme="t-noir").is_error
    assert w.data["style"]["theme"] == "t-noir"

    assert tool(w, "set_theme", theme=3).is_error
    wrong = tool(w, "set_theme", theme="Watercolour")
    assert wrong.is_error and "'Noir'" in wrong.content and "'Claymation'" in wrong.content
    assert not tool(w, "set_theme").is_error
    assert "theme" not in w.data["style"]
    assert w.changes == ["Set the theme to 'Claymation'", "Set the theme to 'Noir'",
                         "Removed the theme"]


def test_no_other_edit_can_slip_in_an_unknown_theme():
    w = Working({"title": "T", "style": {"theme": "t-noir"}}, themes=THEMES)
    result = tool(w, "set_project", changes={"style": {"theme": "made-up"}})
    assert result.is_error and w.data["style"]["theme"] == "t-noir"


def test_a_whole_draft_keeps_the_theme_unless_it_names_another():
    w = Working({"title": "T", "style": {"theme": "t-noir"}}, themes=THEMES)
    tool(w, "replace_spec", spec={"title": "Redrafted"})
    assert w.data["style"]["theme"] == "t-noir"
    tool(w, "replace_spec", spec={"title": "Made up", "style": {"theme": "nope"}})
    assert w.data["style"]["theme"] == "t-noir"
    tool(w, "replace_spec", spec={"title": "Clay", "style": {"theme": "t-clay"}})
    assert w.data["style"]["theme"] == "t-clay"


def test_the_context_lists_the_themes_and_says_which_is_current():
    text = context({"style": {"theme": "t-clay"}}, focus=None, from_scratch=True,
                   themes=THEMES)
    assert "Claymation (id t-clay) [current]: " + CLAY["prompt"] in text
    assert "Noir (id t-noir): " in text
    assert "has none" in context({}, focus=None, from_scratch=True, themes={})


@pytest.fixture
def provider(session, monkeypatch, engine):
    from app.auth import UserCtx
    from app.services.users import ensure_user

    monkeypatch.setattr(worker.queue, "engine", engine)
    ensure_user(session, UserCtx(id=TEST_USER_ID, username=TEST_USER_ID))
    session.add(AIProvider(user_id=TEST_USER_ID, name="Claude", provider_type="anthropic",
                           model="claude-opus-5-5", api_key="sk", is_active=True))
    session.commit()
    scripted = ScriptedProvider(script=[])
    monkeypatch.setattr(worker, "build_provider", lambda session, user_id: scripted)
    return scripted


def test_a_drafted_video_starts_from_the_default_and_keeps_the_assistants_choice(
        auth_client, provider):
    noir = make(auth_client, **NOIR, is_default=True)
    clay = make(auth_client, **CLAY)
    provider.script += [
        says("", call("set_theme", theme="Claymation")),
        says("A clay video."),
    ]
    turn = auth_client.post("/api/assistant/turns",
                            json={"prompt": "A claymation short about rivers"}).json()["data"]
    worker._run(turn["id"])
    # It was shown the list, and started from the default.
    assert f"Noir (id {noir['id']}) [current]" in provider.started["system"][-1]
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["proposed_spec"]["style"]["theme"] == clay["id"]

    made = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project").json()["data"]
    project = auth_client.get(f"/api/projects/{made['project_id']}").json()["data"]
    assert project["spec"]["style"]["theme"] == clay["id"]


def test_a_theme_the_assistant_removed_is_not_put_back_by_the_default(auth_client, provider):
    make(auth_client, **NOIR, is_default=True)
    provider.script += [says("", call("set_theme")), says("No theme.")]
    turn = auth_client.post("/api/assistant/turns", json={"prompt": "Plain, please"}
                            ).json()["data"]
    worker._run(turn["id"])
    made = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project").json()["data"]
    project = auth_client.get(f"/api/projects/{made['project_id']}").json()["data"]
    assert "theme" not in project["spec"]["style"]
