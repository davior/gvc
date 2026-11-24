"""Recipes: the list, their placeholders, running one as an assistant turn, and the
assistant proposing new ones and edits to existing ones, saved only by their button."""

import json

import pytest

from app.assistant import tools as T
from app.assistant import worker
from app.assistant.tools import Working
from app.providers.base import ToolCall
from app.services import recipes as rules
from tests.fake_provider import call, says
from tests.test_assistant_turns import engine_for_worker, provider, start  # noqa: F401 - fixtures

EXPLAINER = {"name": "Explainer", "prompt": "A 60-second explainer about {{topic}} for "
             "{{ Target Audience }}, dated {{date}}.", "tags": ["Short", "short", " edu "]}


def make(client, **body) -> dict:
    res = client.post("/api/recipes", json=body)
    assert res.status_code == 201, res.text
    return res.json()["data"]


def theme(client, name="Noir") -> dict:
    res = client.post("/api/themes", json={"name": name, "prompt": "Black and white."})
    assert res.status_code == 201, res.text
    return res.json()["data"]


# ── placeholders ─────────────────────────────────────────────────────────────

def test_placeholders_match_loosely_and_builtins_are_not_asked_for():
    prompt = "{{Topic}} and {{topic}} for {{target_audience}} on {{date}} in {{ Title }}"
    assert rules.placeholders(prompt) == ["Topic", "target_audience", "date", "Title"]
    assert rules.inputs_of(prompt) == ["Topic", "target_audience"]
    filled = rules.render(prompt, {"topic": "rivers", "Target Audience": "kids", "date": ""})
    # An empty value is no value: left as typed, so it shows it wasn't filled.
    assert filled == "rivers and rivers for kids on {{date}} in {{ Title }}"
    assert rules.render("{{notetitle}}", {"title": "Water"}) == "Water"


# ── the list ─────────────────────────────────────────────────────────────────

def test_recipes_are_made_listed_edited_and_deleted(auth_client):
    made = make(auth_client, **EXPLAINER, defaults={"aspect": "9:16"})
    assert made["tags"] == ["short", "edu"]
    assert made["inputs"] == ["topic", "Target Audience"]
    assert made["defaults"] == {"theme_id": None, "aspect": "9:16", "voice": None}

    listed = auth_client.get("/api/recipes").json()
    assert listed["total"] == 1 and listed["data"][0]["id"] == made["id"]

    changed = auth_client.put(f"/api/recipes/{made['id']}", json={"name": "Short explainer"})
    assert changed.status_code == 200
    body = changed.json()["data"]
    # Left out, left alone.
    assert body["name"] == "Short explainer" and body["prompt"] == EXPLAINER["prompt"]
    assert body["defaults"]["aspect"] == "9:16"

    assert auth_client.delete(f"/api/recipes/{made['id']}").status_code == 204
    assert auth_client.get(f"/api/recipes/{made['id']}").status_code == 404


def test_a_bad_default_is_refused(auth_client):
    res = auth_client.post("/api/recipes", json={**EXPLAINER, "defaults": {"aspect": "4:3"}})
    assert res.status_code == 422
    res = auth_client.post("/api/recipes", json={**EXPLAINER,
                                                 "defaults": {"theme_id": "not-mine"}})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "unknown_theme"


def test_someone_elses_recipes_do_not_exist_for_you(auth_client, switch_user):
    made = make(auth_client, **EXPLAINER)
    switch_user("someone-else")
    assert auth_client.get("/api/recipes").json()["total"] == 0
    assert auth_client.put(f"/api/recipes/{made['id']}", json={"name": "x"}).status_code == 404
    assert auth_client.delete(f"/api/recipes/{made['id']}").status_code == 404


def test_a_gecko_notes_export_imports_as_it_is_and_twice_is_once(auth_client):
    notes_file = [{"name": "Summarise", "prompt": "Summarise {{selected text}}", "tags": ["ai"]},
                  {"name": "Vertical", "prompt": "A teaser", "tags": [],
                   "defaults": {"theme_id": "someone-elses", "aspect": "9:16"}}]
    res = auth_client.post("/api/recipes/import", json={"recipes": notes_file})
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["imported"] == 2
    # Notes' placeholder that means nothing here is just an input.
    assert body["recipes"][0]["inputs"] == ["selected text"]
    vertical = body["recipes"][1]
    assert vertical["defaults"]["aspect"] == "9:16" and vertical["defaults"]["theme_id"] is None
    assert any("theme" in s for s in body["skipped"])

    again = auth_client.post("/api/recipes/import", json={"recipes": notes_file}).json()["data"]
    assert again["imported"] == 0 and len(again["skipped"]) == 2


# ── running one ──────────────────────────────────────────────────────────────

def test_a_run_from_the_list_fills_the_prompt_starts_with_the_defaults_and_names_the_recipe(
        auth_client, provider, engine_for_worker):
    noir = theme(auth_client)
    recipe = make(auth_client, **EXPLAINER, defaults={"theme_id": noir["id"], "aspect": "9:16",
                                                      "voice": {"speed": 1.2}})
    provider.script += [
        says("", call("set_project", changes={"title": "Rivers"})),
        says("A vertical explainer about rivers."),
    ]
    turn = start(auth_client, prompt="", recipe_id=recipe["id"],
                 recipe_inputs={"Topic": "rivers", "target audience": "kids",
                                "date": "24 November 2026"})
    assert turn["prompt"] == "A 60-second explainer about rivers for kids, dated 24 November 2026."
    assert turn["recipe_id"] == recipe["id"] and turn["recipe_name"] == "Explainer"

    worker._run(turn["id"])
    system = provider.started["system"][-1]
    assert "recipe 'Explainer'" in system and "keep them" in system
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    spec = done["proposed_spec"]
    assert spec["output"]["aspect"] == "9:16" and spec["style"]["theme"] == noir["id"]
    assert spec["voice"]["speed"] == 1.2

    made = auth_client.post(f"/api/assistant/turns/{turn['id']}/new-project")
    assert made.status_code == 201, made.text
    project = auth_client.get(f"/api/projects/{made.json()['data']['project_id']}").json()["data"]
    assert project["origin"] == "recipe"
    assert project["spec"]["source"]["recipe"] == {"id": recipe["id"], "name": "Explainer"}


def test_a_run_in_a_project_leaves_its_format_alone_and_says_why(
        auth_client, provider, engine_for_worker):
    recipe = make(auth_client, name="Tighten", prompt="Tighten {{title}}",
                  defaults={"aspect": "9:16"})
    project = auth_client.post("/api/projects", json={"title": "Water Wars"}).json()["data"]
    provider.script += [says("Nothing to change.")]
    turn = start(auth_client, prompt="", project_id=project["id"], recipe_id=recipe["id"])
    assert turn["prompt"] == "Tighten Water Wars"
    worker._run(turn["id"])
    system = provider.started["system"][-1]
    assert "have not been applied" in system
    # The working copy the model was given is the project as it is.
    assert '"9:16"' not in system.split("The video now")[1]


def test_a_run_needs_your_own_recipe_and_a_plain_turn_still_needs_a_prompt(
        auth_client, provider, switch_user):
    recipe = make(auth_client, **EXPLAINER)
    assert auth_client.post("/api/assistant/turns", json={"prompt": ""}).status_code == 422
    switch_user("someone-else")
    res = auth_client.post("/api/assistant/turns", json={"recipe_id": recipe["id"]})
    assert res.status_code in (404, 409)  # not theirs (or, first, no provider of theirs)


# ── the assistant ────────────────────────────────────────────────────────────

def run(w, tool, /, **args):
    return T.execute(w, ToolCall(id="c1", name=tool, arguments=args))


def saved(**recipes) -> dict:
    return {rid: {"name": r.get("name", rid), "prompt": r.get("prompt", "Make {{topic}}"),
                  "tags": r.get("tags", []), "defaults": r.get("defaults", {}),
                  "updated_at": "2026-11-24T10:00:00"} for rid, r in recipes.items()}


def test_the_assistant_reads_a_recipe_whole_before_editing_it():
    long_prompt = "Make {{topic}}. " + "Detail. " * 100
    w = Working({"title": "x"}, recipes=saved(r1={"name": "Explainer", "prompt": long_prompt}))
    listed = json.loads(run(w, "list_recipes").content)
    assert listed[0]["prompt"].endswith("…") and listed[0]["inputs"] == ["topic"]
    whole = json.loads(run(w, "get_recipe", recipe="explainer").content)
    assert whole["prompt"] == long_prompt
    assert run(w, "get_recipe", recipe="nope").is_error


def test_an_update_is_partial_merges_defaults_and_a_second_call_adds_to_the_first():
    w = Working({"title": "x"}, themes={"t1": {"name": "Noir", "prompt": "bw"}},
                recipes=saved(r1={"name": "Explainer", "tags": ["edu"],
                                  "defaults": {"aspect": "16:9", "theme_id": "t1"}}))
    first = run(w, "propose_recipe", op="update", recipe="Explainer",
                prompt="Make {{topic}} in a {{tone}} tone", aspect="9:16")
    assert not first.is_error, first.content
    second = run(w, "propose_recipe", op="update", recipe="r1", tags=["edu", "vertical"])
    assert not second.is_error and w.changes == []
    (p,) = w.recipe_proposals
    assert p["op"] == "update" and p["recipe_id"] == "r1" and p["state"] == "pending"
    assert p["fields"] == ["prompt", "tags", "defaults"]
    # The theme it didn't name is kept; the aspect it did is changed.
    assert p["after"]["defaults"] == {"theme_id": "t1", "aspect": "9:16"}
    assert p["after"]["inputs"] == ["topic", "tone"]
    assert p["before"]["prompt"] == "Make {{topic}}" and p["after"]["name"] == "Explainer"
    # Null clears a default.
    run(w, "propose_recipe", op="update", recipe="r1", theme=None)
    assert w.recipe_proposals[0]["after"]["defaults"] == {"aspect": "9:16"}
    assert run(w, "propose_recipe", op="update", recipe="r1").is_error


def test_proposals_are_checked_and_capped():
    w = Working({"title": "x"}, recipes=saved(r1={"name": "Explainer"}))
    assert run(w, "propose_recipe", op="create", name="Explainer", prompt="x").is_error
    assert run(w, "propose_recipe", op="create", name="New").is_error
    assert run(w, "propose_recipe", op="update", recipe="someone-elses", name="x").is_error
    assert run(w, "propose_recipe", op="update", recipe="r1", prompt="Make {{topic}}").is_error
    assert run(w, "propose_recipe", op="create", name="A", prompt="a", aspect="4:3").is_error
    for name in ("A", "B", "C"):
        assert not run(w, "propose_recipe", op="create", name=name, prompt="p").is_error
    assert run(w, "propose_recipe", op="create", name="D", prompt="p").is_error
    # Changing one of its own new ones rewrites that card.
    assert not run(w, "propose_recipe", op="update", recipe="a", prompt="p2").is_error
    assert [p["after"]["prompt"] for p in w.recipe_proposals] == ["p2", "p", "p"]
    assert not run(w, "propose_recipe", op="delete", recipe="B").is_error
    assert [p["after"]["name"] for p in w.recipe_proposals] == ["A", "C"]


def test_saving_an_edit_writes_only_what_it_changes_and_refuses_one_overtaken(
        auth_client, provider, engine_for_worker):
    recipe = make(auth_client, **EXPLAINER)
    provider.script += [
        says("", call("get_recipe", recipe="Explainer")),
        says("", call("propose_recipe", op="update", recipe="Explainer",
                      prompt="A 30-second explainer about {{topic}} in a {{tone}} tone.",
                      aspect="9:16")),
        says("", call("propose_recipe", op="create", name="Teaser",
                      prompt="A vertical teaser for {{product}}", tags=["Promo"])),
        says("I proposed a shorter explainer and a teaser recipe."),
    ]
    turn = start(auth_client, prompt="Make my explainer shorter and add a teaser recipe")
    worker._run(turn["id"])
    done = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]
    assert done["outcome"] == "" and done["proposed_spec"] is None
    update, create = done["recipes"]
    assert update["fields"] == ["prompt", "defaults"]
    assert update["before"]["prompt"] == EXPLAINER["prompt"]
    assert "base_updated_at" not in update
    # Nothing is saved until the button.
    assert auth_client.get("/api/recipes").json()["total"] == 1

    url = f"/api/assistant/turns/{turn['id']}/recipes"
    res = auth_client.post(f"{url}/{update['recipe_ref']}/save")
    assert res.status_code == 200, res.text
    now = auth_client.get(f"/api/recipes/{recipe['id']}").json()["data"]
    assert now["inputs"] == ["topic", "tone"] and now["defaults"]["aspect"] == "9:16"
    assert now["name"] == "Explainer" and now["tags"] == ["short", "edu"]
    assert auth_client.post(f"{url}/{update['recipe_ref']}/save").status_code == 409

    res = auth_client.post(f"{url}/{create['recipe_ref']}/save")
    made = res.json()["data"]["recipes"][1]
    assert made["state"] == "saved" and made["recipe_id"]
    assert auth_client.get(f"/api/recipes/{made['recipe_id']}").json()["data"]["tags"] == ["promo"]


def test_a_recipe_edited_by_hand_or_deleted_after_the_proposal_is_not_overwritten(
        auth_client, provider, engine_for_worker):
    recipe = make(auth_client, **EXPLAINER)
    other = make(auth_client, name="Other", prompt="Other {{thing}}")
    provider.script += [
        says("", call("propose_recipe", op="update", recipe="Explainer", name="Renamed"),
             call("propose_recipe", op="delete", recipe="Other")),
        says("Proposed."),
    ]
    turn = start(auth_client, prompt="Rename my explainer and delete Other")
    worker._run(turn["id"])
    update, delete = auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]["recipes"]
    assert delete["op"] == "delete" and delete["before"]["name"] == "Other"

    auth_client.put(f"/api/recipes/{recipe['id']}", json={"prompt": "My own edit {{topic}}"})
    auth_client.delete(f"/api/recipes/{other['id']}")
    url = f"/api/assistant/turns/{turn['id']}/recipes"
    res = auth_client.post(f"{url}/{update['recipe_ref']}/save")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "recipe_changed"
    res = auth_client.post(f"{url}/{delete['recipe_ref']}/save")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "recipe_gone"
    assert auth_client.get(f"/api/recipes/{recipe['id']}").json()["data"]["prompt"] == \
        "My own edit {{topic}}"
    discarded = auth_client.post(f"{url}/{update['recipe_ref']}/discard").json()["data"]
    assert discarded["recipes"][0]["state"] == "discarded"


@pytest.mark.parametrize("op", ["update", "delete"])
def test_a_proposal_for_someone_elses_recipe_is_refused(op):
    w = Working({"title": "x"}, recipes={})
    assert run(w, "propose_recipe", op=op, recipe="their-id", name="x").is_error
