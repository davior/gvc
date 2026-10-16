"""Projects over HTTP: the three ways in, editing, history, ownership."""

from tests.conftest import load_fixture


def _create(client, **body):
    res = client.post("/api/projects", json=body)
    assert res.status_code == 201, res.text
    return res.json()["data"]


# ── blank, by hand ──────────────────────────────────────────────────────────

def test_a_blank_project_starts_with_a_title_card_and_one_scene(auth_client):
    project = _create(auth_client, title="Salt Road")
    spec = project["spec"]
    assert project["origin"] == "blank"
    assert project["version"] == 1
    assert [(s["id"], s["kind"]) for s in spec["segments"]] == [("s_title", "card"), ("s_1", "scene")]
    assert spec["segments"][0]["card"]["title"] == "Salt Road"
    # Made by hand: no provenance.
    assert "source" not in spec
    # The defaults are written into the document, so they can be seen and changed.
    assert spec["style"]["transition"] == {"style": "fade", "duration": 0.6}
    assert spec["id"] == project["id"]


def test_a_video_can_be_built_scene_by_scene(auth_client):
    project = _create(auth_client, title="By hand")
    spec = project["spec"]
    spec["segments"][1]["narration"]["beats"][0]["text"] = "First, the desert."
    spec["segments"].append({
        "id": "s_2", "kind": "scene", "label": "Scene 2",
        "narration": {"beats": [{"id": "b1", "text": "Then, the market."}]},
        "transition_in": {"style": "dissolve", "duration": 1.2},
    })
    spec["segments"].append({
        "id": "s_3", "kind": "scene", "label": "Scene 3",
        "narration": {"beats": [{"id": "b1", "text": "And what remains."}]},
    })
    # Reorder: the last scene moves before the second.
    spec["segments"][2], spec["segments"][3] = spec["segments"][3], spec["segments"][2]

    res = auth_client.put(f"/api/projects/{project['id']}", json={"spec": spec, "message": "Scenes"})
    assert res.status_code == 200, res.text
    saved = res.json()["data"]
    assert saved["version"] == 2
    assert [s["id"] for s in saved["spec"]["segments"]] == ["s_title", "s_1", "s_3", "s_2"]
    assert saved["spec"]["segments"][3]["transition_in"] == {"style": "dissolve", "duration": 1.2}


def test_a_title_is_mirrored_from_the_spec(auth_client):
    project = _create(auth_client, title="One")
    spec = {**project["spec"], "title": "Two"}
    auth_client.put(f"/api/projects/{project['id']}", json={"spec": spec})
    listed = auth_client.get("/api/projects").json()
    assert listed["total"] == 1
    assert listed["data"][0]["title"] == "Two"


# ── pasted ──────────────────────────────────────────────────────────────────

def test_a_pasted_spec_is_migrated_and_keeps_its_provenance(auth_client):
    project = _create(auth_client, spec=load_fixture("salt_road_0_1.json"))
    assert project["origin"] == "pasted"
    assert project["spec"]["spec_version"] == "0.2"
    assert project["spec"]["source"]["kind"] == "note"
    # The server owns the id, whatever the paste said.
    assert project["spec"]["id"] == project["id"] != "vid_salt_road_01"


def test_an_invalid_spec_is_refused_with_paths_the_editor_can_point_at(auth_client):
    res = auth_client.post("/api/projects", json={"spec": {"voice": {"speed": 9}}})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "invalid_spec"
    assert detail["message"] == "The spec has 1 problem"
    assert detail["issues"] == [{"path": ["voice", "speed"],
                                 "message": "Input should be less than or equal to 2"}]
    assert auth_client.get("/api/projects").json()["total"] == 0


def test_saving_an_invalid_spec_changes_nothing(auth_client):
    project = _create(auth_client, title="Keep me")
    bad = {**project["spec"], "segments": [{"id": "x", "kind": "clip"}]}
    res = auth_client.put(f"/api/projects/{project['id']}", json={"spec": bad})
    assert res.status_code == 422
    after = auth_client.get(f"/api/projects/{project['id']}").json()["data"]
    assert after["version"] == 1
    assert after["spec"] == project["spec"]


# ── pushed from Notes ───────────────────────────────────────────────────────

def test_a_note_pushed_from_notes_becomes_an_ordinary_project(auth_client):
    res = auth_client.post("/api/projects/import", json={"spec": load_fixture("notes_push_0_1.json")})
    assert res.status_code == 201, res.text
    project = res.json()["data"]
    assert project["origin"] == "note"
    assert project["title"] == "The Salt Road"
    assert project["spec"]["source"]["note_id"] == "note-123"
    # Its pictures and music are still files in the note until M1 copies them to GAM.
    assert project["pending_note_media"] == 3

    # From here it is edited in GVC like any other.
    spec = project["spec"]
    spec["segments"][2]["transition_in"] = {"style": "dissolve"}
    res = auth_client.put(f"/api/projects/{project['id']}", json={"spec": spec})
    assert res.status_code == 200
    assert res.json()["data"]["spec"]["source"]["note_id"] == "note-123"


def test_a_push_without_provenance_is_still_marked_as_from_notes(auth_client):
    res = auth_client.post("/api/projects/import", json={"spec": {"spec_version": "0.1", "title": "x"}})
    source = res.json()["data"]["spec"]["source"]
    assert source["kind"] == "note"
    assert source["imported_at"].endswith("Z")


# ── history ─────────────────────────────────────────────────────────────────

def test_every_save_is_a_version_and_a_revert_is_another(auth_client):
    project = _create(auth_client, title="v1")
    pid = project["id"]
    for title in ("v2", "v3"):
        auth_client.put(f"/api/projects/{pid}", json={"spec": {**project["spec"], "title": title},
                                                      "message": f"to {title}"})

    versions = auth_client.get(f"/api/projects/{pid}/versions").json()
    assert versions["total"] == 3
    assert [v["seq"] for v in versions["data"]] == [3, 2, 1]
    first = versions["data"][-1]

    detail = auth_client.get(f"/api/projects/{pid}/versions/{first['id']}").json()["data"]
    assert detail["spec"]["title"] == "v1"

    res = auth_client.post(f"/api/projects/{pid}/revert/{first['id']}")
    assert res.status_code == 200
    reverted = res.json()["data"]
    assert reverted["title"] == "v1"
    assert reverted["version"] == 4

    latest = auth_client.get(f"/api/projects/{pid}/versions?limit=1").json()["data"][0]
    assert latest["message"] == "Reverted to version 1"
    assert latest["reverted_from"] == first["id"]


# ── ownership ───────────────────────────────────────────────────────────────

def test_another_users_project_does_not_exist_for_you(auth_client, switch_user):
    project = _create(auth_client, title="Mine")
    pid = project["id"]
    version_id = auth_client.get(f"/api/projects/{pid}/versions").json()["data"][0]["id"]

    switch_user("someone-else")
    assert auth_client.get("/api/projects").json()["total"] == 0
    for method, url in [
        ("get", f"/api/projects/{pid}"),
        ("put", f"/api/projects/{pid}"),
        ("delete", f"/api/projects/{pid}"),
        ("get", f"/api/projects/{pid}/versions"),
        ("post", f"/api/projects/{pid}/revert/{version_id}"),
    ]:
        kwargs = {"json": {"spec": project["spec"]}} if method == "put" else {}
        res = getattr(auth_client, method)(url, **kwargs)
        assert res.status_code == 404, (method, url)
        assert res.json()["detail"]["code"] == "not_found"


def test_a_version_of_another_project_cannot_be_reverted_to(auth_client):
    a = _create(auth_client, title="A")
    b = _create(auth_client, title="B")
    b_version = auth_client.get(f"/api/projects/{b['id']}/versions").json()["data"][0]["id"]
    assert auth_client.post(f"/api/projects/{a['id']}/revert/{b_version}").status_code == 404


def test_delete_removes_the_project_and_its_history(auth_client, session):
    from sqlmodel import select

    from app.models.project import ProjectVersion

    project = _create(auth_client, title="Gone")
    assert auth_client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert auth_client.get(f"/api/projects/{project['id']}").status_code == 404
    assert session.exec(select(ProjectVersion)).all() == []


# ── the format endpoints ────────────────────────────────────────────────────

def test_validate_answers_rather_than_fails(auth_client):
    good = auth_client.post("/api/spec/validate", json=load_fixture("salt_road_0_1.json")).json()["data"]
    assert good["valid"] is True
    assert good["spec"]["spec_version"] == "0.2"

    bad = auth_client.post("/api/spec/validate", json=[1, 2]).json()["data"]
    assert bad["valid"] is False and bad["issues"]


def test_the_schema_carries_the_limits_the_editor_uses(auth_client):
    schema = auth_client.get("/api/spec/schema").json()["data"]
    voice = schema["$defs"]["Voice"]["properties"]["speed"]
    assert (voice["minimum"], voice["maximum"]) == (0.5, 2.0)
    assert "Frame" in schema["$defs"]
