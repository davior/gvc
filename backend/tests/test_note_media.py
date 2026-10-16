"""Copying a pushed note's media into GAM, which finishes the hand-off from Notes."""

from app.config import settings
from tests.conftest import load_fixture
from tests.fake_siblings import NOTES


def _push(client, spec=None):
    res = client.post("/api/projects/import", json={"spec": spec or load_fixture("notes_push_0_1.json")})
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _copy(client, project_id):
    return client.post(f"/api/projects/{project_id}/copy-note-media")


def test_every_note_file_moves_into_gam_under_the_same_key(auth_client, siblings):
    siblings.notes_files = {
        "/media/u1/map.png": b"map", "/media/u1/market.jpg": b"market", "/media/u1/theme.mp3": b"mp3",
    }
    project = _push(auth_client)
    before = project["spec"]

    res = _copy(auth_client, project["id"])

    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert sorted(body["copied"]) == ["a1", "a2", "a3"]
    assert body["failed"] == []
    after = body["project"]
    assert after["pending_note_media"] == 0
    assert after["version"] == project["version"] + 1
    for key in ("a1", "a2", "a3"):
        assert after["spec"]["assets"][key]["from"] == "gam"
        # The type the note used it as survives: a videoFile block stays a video.
        assert after["spec"]["assets"][key]["type"] == before["assets"][key]["type"]
    # Nothing that pointed at those keys needed to change.
    assert after["spec"]["segments"] == before["segments"]
    assert after["spec"]["audio_tracks"] == before["audio_tracks"]
    assert [u["filename"] for u in siblings.uploads] == ["map.png", "market.jpg", "theme.mp3"]

    history = auth_client.get(f"/api/projects/{project['id']}/versions?limit=1").json()["data"][0]
    assert history["message"] == "Copied 3 files from the note into GAM"


def test_a_file_that_fails_stays_in_the_note_to_retry(auth_client, siblings):
    siblings.notes_files = {"/media/u1/map.png": b"map", "/media/u1/theme.mp3": b"mp3"}
    siblings.refuse_uploads = ["theme.mp3"]
    project = _push(auth_client)

    body = _copy(auth_client, project["id"]).json()["data"]

    assert body["copied"] == ["a1"]
    failed = {f["key"]: f["message"] for f in body["failed"]}
    assert failed["a2"] == "The note no longer has this file"
    assert failed["a3"] == "That file type is not supported"
    assert body["project"]["pending_note_media"] == 2
    assert body["project"]["spec"]["assets"]["a2"]["from"] == "notes"

    # Retry once the note has it again: only what is left is fetched.
    siblings.notes_files["/media/u1/market.jpg"] = b"market"
    siblings.refuse_uploads = []
    siblings.requests.clear()
    retry = _copy(auth_client, project["id"]).json()["data"]
    assert sorted(retry["copied"]) == ["a2", "a3"]
    assert retry["project"]["pending_note_media"] == 0


def test_nothing_copied_is_no_new_version(auth_client, siblings):
    project = _push(auth_client)
    body = _copy(auth_client, project["id"]).json()["data"]
    assert body["copied"] == []
    assert body["project"]["version"] == project["version"]


def test_a_pasted_url_cannot_make_this_server_fetch_anywhere_else(auth_client, siblings):
    spec = {"spec_version": "0.2", "assets": {
        "a_evil": {"from": "notes", "url": "http://169.254.169.254/latest/meta-data", "type": "image"},
        "a_up": {"from": "notes", "url": "/media/../etc/passwd", "type": "image"},
        "a_api": {"from": "notes", "url": "/api/notes", "type": "image"},
    }}
    project = _push(auth_client, spec)
    body = _copy(auth_client, project["id"]).json()["data"]
    assert {f["key"] for f in body["failed"]} == {"a_evil", "a_up", "a_api"}
    assert siblings.requests == []


def test_a_file_over_the_cap_is_refused_while_it_streams(auth_client, siblings, monkeypatch):
    monkeypatch.setattr(settings, "note_media_max_mb", 1)
    siblings.notes_files = {"/media/u1/map.png": b"x" * (2 * 1024 * 1024)}
    project = _push(auth_client, {"spec_version": "0.2", "assets": {
        "a1": {"from": "notes", "url": "/media/u1/map.png", "type": "image"}}})
    body = _copy(auth_client, project["id"]).json()["data"]
    assert body["failed"] == [{"key": "a1", "message": "Larger than 1 MB"}]
    assert siblings.uploads == []


def test_files_come_only_from_the_configured_notes(auth_client, siblings):
    siblings.notes_files = {"/media/u1/map.png": b"map"}
    project = _push(auth_client, {"spec_version": "0.2", "assets": {
        "a1": {"from": "notes", "url": "/media/u1/map.png", "type": "image"}}})
    _copy(auth_client, project["id"])
    assert str(siblings.requests[0].url) == f"{NOTES}/media/u1/map.png"


def test_another_users_project_cannot_be_copied(auth_client, siblings, switch_user):
    project = _push(auth_client)
    switch_user("someone-else")
    assert _copy(auth_client, project["id"]).status_code == 404
    assert siblings.requests == []
