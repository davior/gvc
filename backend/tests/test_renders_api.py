"""Rendering over HTTP: estimate, start, follow, fetch, cancel; and who may."""

import json
import time

import pytest
from jose import jwt

from app.config import settings
from app.render import ffmpeg as F
from app.render import worker
from tests.test_render_integration import SPEC

needs_ffmpeg = pytest.mark.skipif(not F.ffmpeg_available(), reason="needs ffmpeg")


@pytest.fixture
def engine_for_worker(engine, monkeypatch):
    """The worker opens its own sessions; point them at the test database."""
    monkeypatch.setattr(worker.queue, "engine", engine)
    return engine


def _project(client, spec=SPEC):
    res = client.post("/api/projects", json={"spec": spec})
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _start(client, project_id, preview=True, **kwargs):
    return client.post(f"/api/projects/{project_id}/renders", json={"preview": preview}, **kwargs)


def test_the_estimate_says_how_long_and_what_would_stop_a_render(auth_client):
    data = json.loads(json.dumps(SPEC))
    data["assets"]["a_find"] = {"from": "search", "query": "a dry riverbed"}
    data["segments"][1]["visual"] = {"asset": "a_find"}
    project = _project(auth_client, data)

    body = auth_client.post(f"/api/projects/{project['id']}/estimate").json()["data"]

    # card 3.5 + valley (~58 chars / 15 + pauses) + river (2.5 floor) + the 3 s clip
    assert 10 < body["seconds"] < 16
    assert body["narration_chars"] == len("The valley used to run clear.") + len(
        "Now every drop is fought over.") + len("The river is lower every year.")
    assert body["blocks_render"] == ["Footage still to find: “a dry riverbed”."]
    assert body["blocks_preview"] == []


def test_a_full_render_is_refused_until_the_placeholders_are_found(auth_client):
    data = json.loads(json.dumps(SPEC))
    data["assets"]["a_find"] = {"from": "search", "query": "a dry riverbed"}
    data["segments"][1]["visual"] = {"asset": "a_find"}
    project = _project(auth_client, data)

    refused = _start(auth_client, project["id"], preview=False)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_renderable"
    assert "a dry riverbed" in refused.json()["detail"]["message"]
    # A preview draws it as a slate instead.
    assert _start(auth_client, project["id"], preview=True).status_code == 202


def test_one_render_at_a_time_per_project(auth_client):
    project = _project(auth_client)
    first = _start(auth_client, project["id"])
    assert first.status_code == 202
    assert first.json()["data"]["status"] == "queued"
    assert first.json()["data"]["version"] == 1
    again = _start(auth_client, project["id"])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "render_running"


@needs_ffmpeg
def test_a_render_runs_as_its_requester_and_its_files_are_served_signed(
        client, library, engine_for_worker):
    token = jwt.encode({"sub": "notes-user-1", "username": "gecko", "exp": int(time.time()) + 3600},
                       settings.jwt_secret_key, algorithm="HS256")
    auth = {"Authorization": f"Bearer {token}"}
    project = client.post("/api/projects", json={"spec": SPEC}, headers=auth).json()["data"]
    job = _start(client, project["id"], headers=auth).json()["data"]

    worker._run(job["id"])

    done = client.get(f"/api/renders/{job['id']}", headers=auth).json()["data"]
    assert done["status"] == "done", done
    assert done["progress"] == 100
    assert 11 < done["duration"] < 17
    assert done["narration_chars"] > 0
    # Media and narration were fetched as the user who asked, nobody else.
    sibling_calls = [r for r in library.requests if not r.url.path.startswith("/media/")]
    assert sibling_calls and all(r.headers.get("authorization") == f"Bearer {token}"
                                 for r in sibling_calls)

    video = client.get(done["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    ranged = client.get(done["video_url"], headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100
    assert client.get(done["poster_url"]).status_code == 200
    tampered = done["video_url"].replace("video.mp4", "poster.jpg")
    assert client.get(tampered).status_code == 403

    listed = client.get(f"/api/projects/{project['id']}/renders", headers=auth).json()
    assert [r["id"] for r in listed["data"]] == [job["id"]]

    # Deleting the project takes its renders, files and all, with it.
    assert client.delete(f"/api/projects/{project['id']}", headers=auth).status_code == 204
    assert not (worker.renders_dir() / job["id"]).exists()


@needs_ffmpeg
def test_a_render_that_cannot_reach_notes_says_why(auth_client, library, engine_for_worker):
    library.speech_provider = None
    project = _project(auth_client)
    job = _start(auth_client, project["id"]).json()["data"]
    worker._run(job["id"])
    failed = auth_client.get(f"/api/renders/{job['id']}").json()["data"]
    assert failed["status"] == "error"
    assert "gecko-notes#211" in failed["error"]
    assert failed["video_url"] is None


def test_a_render_queued_before_a_restart_is_ended_not_rerun(auth_client, engine_for_worker,
                                                             monkeypatch):
    project = _project(auth_client)
    job = _start(auth_client, project["id"]).json()["data"]
    worker._tokens.clear()  # what a restart does to the in-memory tokens
    worker.queue.recover_pending()
    ended = auth_client.get(f"/api/renders/{job['id']}").json()["data"]
    assert ended["status"] == "error"
    assert "restart" in ended["error"]


def test_a_queued_render_can_be_cancelled(auth_client, engine_for_worker):
    project = _project(auth_client)
    job = _start(auth_client, project["id"]).json()["data"]
    cancelled = auth_client.post(f"/api/renders/{job['id']}/cancel").json()["data"]
    assert cancelled["status"] == "cancelled"
    worker._run(job["id"])  # the worker, reaching it later, leaves it alone
    assert auth_client.get(f"/api/renders/{job['id']}").json()["data"]["status"] == "cancelled"


def test_another_users_render_does_not_exist_for_you(auth_client, switch_user):
    project = _project(auth_client)
    job = _start(auth_client, project["id"]).json()["data"]
    switch_user("someone-else")
    for method, url in (("get", f"/api/renders/{job['id']}"),
                        ("post", f"/api/renders/{job['id']}/cancel"),
                        ("delete", f"/api/renders/{job['id']}"),
                        ("post", f"/api/projects/{project['id']}/renders"),
                        ("get", f"/api/projects/{project['id']}/renders")):
        kwargs = {"json": {"preview": True}} if url.endswith("/renders") and method == "post" else {}
        assert getattr(auth_client, method)(url, **kwargs).status_code == 404, (method, url)
