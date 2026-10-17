"""Generating pictures and clips for placeholders, through a faked GAM."""

import pytest

from app.generation.catalogue import (
    CatalogueError, default_params, estimate, kind_for, pick_model,
)
from tests.fake_siblings import GEN_MODELS

FLUX, EDIT, KLING, VEO = GEN_MODELS


# ── choosing models and options (pure) ───────────────────────────────────────

def test_the_kind_follows_the_placeholder_and_its_base_images():
    assert kind_for("image", False) == "text_to_image"
    assert kind_for("image", True) == "image_to_image"
    assert kind_for("video", True) == "image_to_video"
    with pytest.raises(CatalogueError, match="music"):
        kind_for("music", False)


def test_the_first_model_of_a_kind_unless_one_is_asked_for():
    assert pick_model(GEN_MODELS, "image_to_video")["id"] == "m-kling"
    assert pick_model(GEN_MODELS, "image_to_video", "m-veo")["id"] == "m-veo"
    with pytest.raises(CatalogueError):
        pick_model(GEN_MODELS, "image_to_video", "m-flux")


def test_options_come_from_the_models_own_lists_with_their_own_types():
    # FLUX names sizes; the video's aspect picks the matching one.
    assert default_params(FLUX, aspect="16:9", outputs=3) == {
        "image_size": "landscape_16_9", "num_outputs": 3}
    assert default_params(FLUX, aspect="9:16")["image_size"] == "portrait_16_9"
    # A model with ratios gets the ratio itself.
    assert default_params(EDIT, aspect="16:9")["aspect_ratio"] == "16:9"
    # Durations are matched by number and passed as the catalogue spells them.
    assert default_params(KLING, aspect="16:9")["duration"] == "5"
    assert default_params(VEO, aspect="16:9", duration="6")["duration"] == "6s"
    # Never more outputs than the model makes.
    assert default_params(KLING, aspect="16:9", outputs=4)["num_outputs"] == 1


def test_estimates_by_price_unit():
    assert estimate(KLING, {"duration": "10", "num_outputs": 1}) == pytest.approx(0.7)
    assert estimate(EDIT, {"num_outputs": 2}) == pytest.approx(0.078)
    # FLUX is priced per megapixel: 1024x576 is 0.59 MP.
    assert estimate(FLUX, {"image_size": "landscape_16_9", "num_outputs": 1}) == pytest.approx(
        0.003 * 1024 * 576 / 1e6, abs=1e-4)
    assert estimate({"unit_price": None}, {}) is None


# ── over HTTP ────────────────────────────────────────────────────────────────

SPEC = {
    "title": "Water Wars",
    "assets": {
        "a_map": {"from": "gam", "id": "p", "type": "image"},
        "a_dam": {"from": "generate", "type": "image", "prompt": "A dam at dusk"},
        "a_flood": {"from": "generate", "type": "video", "prompt": "Water rising",
                    "base_assets": ["a_map"]},
        "a_song": {"from": "generate", "type": "music", "prompt": "A calm theme"},
    },
    "segments": [
        {"id": "s_dam", "kind": "scene", "visual": {"asset": "a_dam"}},
        {"id": "s_flood", "kind": "scene", "visual": {"asset": "a_flood"}},
    ],
}


@pytest.fixture
def project(auth_client, siblings):
    res = auth_client.post("/api/projects", json={"spec": SPEC})
    assert res.status_code == 201, res.text
    return res.json()["data"]


def start(client, project_id, **body):
    return client.post(f"/api/projects/{project_id}/generations", json=body,
                       headers={"Authorization": "Bearer user-token"})


def test_a_picture_placeholder_is_generated_as_its_owner_in_the_videos_aspect(
        auth_client, project, siblings):
    res = start(auth_client, project["id"], asset_key="a_dam", outputs=2)
    assert res.status_code == 202, res.text
    row = res.json()["data"]
    assert (row["kind"], row["status"], row["model_label"]) == (
        "text_to_image", "queued", "FLUX.1 [schnell]")
    assert row["estimate"] == pytest.approx(2 * 0.003 * 1024 * 576 / 1e6, abs=1e-4)
    [sent] = siblings.generations
    assert sent["authorization"] == "Bearer user-token"
    assert sent["prompt"] == "A dam at dusk" and sent["base_asset_ids"] == []
    assert sent["params"] == {"image_size": "landscape_16_9", "num_outputs": 2}


def test_a_clip_is_made_from_its_base_picture(auth_client, project, siblings):
    res = start(auth_client, project["id"], asset_key="a_flood", model_id="m-veo", duration="8")
    assert res.status_code == 202, res.text
    sent = siblings.generations[0]
    assert sent["model_id"] == "m-veo" and sent["base_asset_ids"] == ["p"]
    assert sent["params"] == {"aspect_ratio": "16:9", "duration": "8s", "num_outputs": 1}


def test_what_cannot_be_generated_says_why(auth_client, project, siblings):
    music = start(auth_client, project["id"], asset_key="a_song")
    assert music.status_code == 422 and music.json()["detail"]["code"] == "cannot_generate"
    real = start(auth_client, project["id"], asset_key="a_map")
    assert real.json()["detail"]["code"] == "not_a_placeholder"
    draft = {**SPEC, "assets": {**SPEC["assets"], "a_flood": {
        "from": "generate", "type": "video", "prompt": "Water rising"}}}
    no_base = start(auth_client, project["id"], asset_key="a_flood", draft_spec=draft)
    assert no_base.json()["detail"]["code"] == "needs_base_image"
    assert siblings.generations == []


def test_a_placeholder_only_in_the_unsaved_draft_can_be_generated(auth_client, project, siblings):
    draft = {**SPEC, "assets": {**SPEC["assets"], "a_new": {
        "from": "generate", "type": "image", "prompt": "A canal"}}}
    res = start(auth_client, project["id"], asset_key="a_new", draft_spec=draft)
    assert res.status_code == 202 and siblings.generations[0]["prompt"] == "A canal"


def test_reading_the_list_follows_each_job_to_done(auth_client, project, siblings):
    row = start(auth_client, project["id"], asset_key="a_dam").json()["data"]
    job = siblings.gen_jobs["job-1"]
    job.update(status="processing", stage="Generating", progress=40, detail="0:12 so far")
    listed = auth_client.get(f"/api/projects/{project['id']}/generations").json()["data"]
    assert (listed[0]["status"], listed[0]["stage"], listed[0]["progress"]) == (
        "processing", "Generating", 40)

    job.update(status="done", progress=100, result_asset_id="g1", result_asset_ids=["g1", "g2"])
    listed = auth_client.get(f"/api/projects/{project['id']}/generations").json()["data"]
    assert listed[0]["status"] == "done" and listed[0]["result_ids"] == ["g1", "g2"]
    # A finished one isn't asked about again.
    siblings.requests.clear()
    auth_client.get(f"/api/projects/{project['id']}/generations")
    assert not [r for r in siblings.requests if "/api/activity/" in r.url.path]

    used = auth_client.post(f"/api/generations/{row['id']}/use", json={"asset_id": "g2"})
    assert used.json()["data"]["used_id"] == "g2"
    assert auth_client.post(f"/api/generations/{row['id']}/use",
                            json={"asset_id": "other"}).status_code == 400


def test_a_running_generation_can_be_stopped(auth_client, project, siblings):
    row = start(auth_client, project["id"], asset_key="a_dam").json()["data"]
    stopped = auth_client.delete(f"/api/generations/{row['id']}").json()["data"]
    assert stopped["status"] == "cancelled"
    assert siblings.gen_jobs["job-1"]["status"] == "cancelled"


def test_no_fal_key_says_where_to_add_one(auth_client, project, siblings):
    siblings.fal_key = False
    res = start(auth_client, project["id"], asset_key="a_dam")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "fal_key_missing"
    assert "/settings" in res.json()["detail"]["message"]


def test_the_catalogue_with_prices(auth_client, siblings):
    models = auth_client.get("/api/gam/generation-models").json()["data"]
    assert [m["id"] for m in models] == ["m-flux", "m-edit", "m-kling", "m-veo"]
    assert models[2]["price"] == "$0.07 a second"


def test_someone_elses_generations_do_not_exist_for_you(auth_client, project, siblings,
                                                        switch_user):
    row = start(auth_client, project["id"], asset_key="a_dam").json()["data"]
    switch_user("someone-else")
    assert auth_client.get(f"/api/projects/{project['id']}/generations").status_code == 404
    assert auth_client.delete(f"/api/generations/{row['id']}").status_code == 404
    assert auth_client.post(f"/api/generations/{row['id']}/use",
                            json={"asset_id": "x"}).status_code == 404


def test_deleting_the_project_deletes_its_generations(auth_client, session, project, siblings):
    from sqlmodel import select

    from app.models.generation import Generation

    start(auth_client, project["id"], asset_key="a_dam")
    assert auth_client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert session.exec(select(Generation)).all() == []
