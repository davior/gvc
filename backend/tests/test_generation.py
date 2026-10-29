"""Generating pictures and clips for placeholders, through a faked GAM."""

import pytest

from app.generation.catalogue import (
    CatalogueError, default_params, estimate, kind_for, pick_model, target_size,
)
from tests.fake_siblings import GEN_MODELS

FLUX, EDIT, KLING, VEO = GEN_MODELS

# FLUX as a GAM with `custom_size` lists it (gam: the FLUX custom-size migration).
LIMITS = {"max_width": 3072, "max_height": 3072, "multiple_of": 16, "max_pixels": 5_000_000}
SIZED_FLUX = {**FLUX, "options": {**FLUX["options"], "custom_size": LIMITS}}
NANO_BANANA = {"id": "m-nano", "kind": "text_to_image", "unit_price": 0.08, "price_unit": "image",
               "options": {"aspect_ratios": ["auto", "16:9", "1:1", "9:16"],
                           "resolutions": ["0.5K", "1K", "2K", "4K"], "max_outputs": 4}}
SEEDREAM = {"id": "m-seedream", "kind": "image_to_image", "unit_price": 0.04, "price_unit": "image",
            "options": {"image_sizes": ["auto_2K", "auto_4K"], "max_outputs": 4}}


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
    # FLUX is priced per megapixel, which fal counts as whole units of 1024², rounded up:
    # 1024x576 is one, and 2880x1616 (4.4 of them) is five.
    assert estimate(FLUX, {"image_size": "landscape_16_9", "num_outputs": 1}) == pytest.approx(0.003)
    assert estimate(FLUX, {"width": 2880, "height": 1616, "num_outputs": 2}) == pytest.approx(0.03)
    assert estimate({"unit_price": None}, {}) is None


# ── sizing a picture for the video ───────────────────────────────────────────

def test_the_target_is_the_frame_with_headroom_in_the_pictures_own_aspect():
    assert target_size("16:9", "1080p") == (2880, 1620)
    assert target_size("16:9", "720p") == (1920, 1080)
    # The output's short edge sets the scale, whatever shape the picture is.
    assert target_size("1:1", "1080p") == (1620, 1620)
    assert target_size("9:16", "4k") == (3240, 5760)


def test_a_model_that_takes_any_size_is_asked_for_the_target():
    params = default_params(SIZED_FLUX, aspect="16:9", outputs=2, target=(2880, 1620))
    # 1620 is rounded down to FLUX's sixteens here rather than by GAM.
    assert params == {"width": 2880, "height": 1616, "num_outputs": 2}


def test_a_target_beyond_the_models_limits_shrinks_with_its_aspect_kept():
    params = default_params(SIZED_FLUX, aspect="16:9", target=target_size("16:9", "4k"))
    width, height = params["width"], params["height"]
    assert width * height <= LIMITS["max_pixels"]
    assert width <= 3072 and height <= 3072
    assert width % 16 == 0 and height % 16 == 0
    assert width / height == pytest.approx(16 / 9, rel=0.01)
    # Portrait is clamped by its height.
    tall = default_params(SIZED_FLUX, aspect="9:16", target=target_size("9:16", "4k"))
    assert tall["height"] <= 3072 and tall["width"] < tall["height"]


def test_size_tiers_take_the_nearest_to_the_target_never_below_the_frame():
    def resolution(output):
        return default_params(NANO_BANANA, aspect="16:9", target=target_size("16:9", output))["resolution"]

    # 2K is 1.43x a 1080p frame: near enough to 1.5x, where 4K would be three times it.
    assert resolution("1080p") == "2K"
    assert resolution("4k") == "4K"
    # 720p's target sits between 1K and 2K, a little nearer 1K, which is still above
    # the frame (about 1376x768 at 16:9).
    assert resolution("720p") == "1K"
    params = default_params(NANO_BANANA, aspect="16:9", target=target_size("16:9", "1080p"))
    assert params["aspect_ratio"] == "16:9"


def test_a_tier_below_the_frame_is_never_chosen_while_a_larger_one_exists():
    small = {**NANO_BANANA, "options": {**NANO_BANANA["options"], "resolutions": ["1K", "4K"]}}
    # 1K is nearer 1.5x a 1080p frame by ratio than 4K is, but it is smaller than the frame.
    assert default_params(small, aspect="16:9", target=target_size("16:9", "1080p"))["resolution"] == "4K"
    # With nothing larger, the largest there is.
    only_small = {**NANO_BANANA, "options": {**NANO_BANANA["options"], "resolutions": ["0.5K", "1K"]}}
    assert default_params(only_small, aspect="16:9", target=target_size("16:9", "4k"))["resolution"] == "1K"


def test_seedreams_automatic_sizes_are_tiers_too():
    assert default_params(SEEDREAM, aspect="16:9", target=target_size("16:9", "1080p"))["image_size"] == "auto_2K"
    assert default_params(SEEDREAM, aspect="16:9", target=target_size("16:9", "4k"))["image_size"] == "auto_4K"


def test_without_custom_sizes_flux_keeps_its_preset():
    # A GAM older than `custom_size`: the preset for the aspect, as before.
    assert default_params(FLUX, aspect="16:9", target=(2880, 1620)) == {
        "image_size": "landscape_16_9", "num_outputs": 1}
    # And no target, no change at all.
    assert default_params(SIZED_FLUX, aspect="16:9") == {"image_size": "landscape_16_9", "num_outputs": 1}


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
    assert row["estimate"] == pytest.approx(2 * 0.003)
    [sent] = siblings.generations
    assert sent["authorization"] == "Bearer user-token"
    assert sent["prompt"] == "A dam at dusk" and sent["base_asset_ids"] == []
    assert sent["params"] == {"image_size": "landscape_16_9", "num_outputs": 2}


def test_a_picture_is_sized_for_the_video_when_the_model_takes_any_size(
        auth_client, project, siblings):
    siblings.gen_models[0] = dict(SIZED_FLUX)
    res = start(auth_client, project["id"], asset_key="a_dam")
    assert res.status_code == 202, res.text
    # 1.5x a 1080p 16:9 frame, in FLUX's sixteens; five fal megapixels.
    assert siblings.generations[0]["params"] == {"width": 2880, "height": 1616, "num_outputs": 1}
    assert res.json()["data"]["estimate"] == pytest.approx(5 * 0.003)


def test_the_videos_resolution_and_the_pictures_aspect_set_the_size(auth_client, siblings):
    siblings.gen_models[0] = dict(SIZED_FLUX)
    spec = {**SPEC, "output": {"aspect": "16:9", "resolution": "720p"},
            "assets": {**SPEC["assets"], "a_dam": {**SPEC["assets"]["a_dam"], "aspect": "1:1"}}}
    project = auth_client.post("/api/projects", json={"spec": spec}).json()["data"]
    assert start(auth_client, project["id"], asset_key="a_dam").status_code == 202
    assert siblings.generations[0]["params"] == {"width": 1072, "height": 1072, "num_outputs": 1}


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


# ── a clip from the prompt alone: picture, then animate ──────────────────────

NO_BASE = {**SPEC, "assets": {**SPEC["assets"], "a_flood": {
    "from": "generate", "type": "video", "prompt": "Water rising"}}}


def _list(client, project_id):
    return client.get(f"/api/projects/{project_id}/generations").json()["data"]


def test_a_clip_from_a_prompt_makes_its_picture_first_then_animates_it(
        auth_client, project, siblings):
    res = start(auth_client, project["id"], asset_key="a_flood", draft_spec=NO_BASE,
                make_picture=True, picture_prompt="A flooded valley", model_id="m-veo",
                duration="8")
    assert res.status_code == 202, res.text
    row = res.json()["data"]
    [picture] = siblings.generations
    assert picture["model_id"] == "m-flux" and picture["prompt"] == "A flooded valley"
    assert picture["base_asset_ids"] == []
    assert picture["params"] == {"image_size": "landscape_16_9", "num_outputs": 1}
    assert row["stage"].startswith("Making the picture")
    assert row["model_label"] == "FLUX.1 [schnell] → Veo 3.1 Fast"
    # Both runs, priced together.
    assert row["estimate"] == pytest.approx(0.1 * 8 + 0.003)

    siblings.gen_jobs["job-1"].update(status="processing", stage="Generating", progress=50)
    listed = _list(auth_client, project["id"])[0]
    assert listed["stage"] == "Making the picture · Generating"
    assert listed["result_ids"] == [] and listed["status"] == "processing"

    # The picture is done: its output is never offered for the clip's placeholder.
    siblings.gen_jobs["job-1"].update(status="done", result_asset_ids=["pic-1"])
    listed = _list(auth_client, project["id"])[0]
    assert listed["status"] == "queued" and listed["result_ids"] == []
    assert listed["picture_id"] == "pic-1"
    clip = siblings.generations[1]
    assert clip["model_id"] == "m-veo" and clip["prompt"] == "Water rising"
    assert clip["base_asset_ids"] == ["pic-1"]
    assert clip["params"]["duration"] == "8s"

    siblings.gen_jobs["job-2"].update(status="done", result_asset_ids=["clip-1"])
    listed = _list(auth_client, project["id"])[0]
    assert listed["status"] == "done" and listed["result_ids"] == ["clip-1"]
    assert len(siblings.generations) == 2


def test_a_failed_picture_says_so_and_starts_no_clip(auth_client, project, siblings):
    start(auth_client, project["id"], asset_key="a_flood", draft_spec=NO_BASE, make_picture=True)
    siblings.gen_jobs["job-1"].update(status="error", error_message="Content refused")
    listed = _list(auth_client, project["id"])[0]
    assert listed["status"] == "error"
    assert listed["error"] == "Making the picture failed: Content refused"
    assert len(siblings.generations) == 1


def test_a_clip_that_cannot_start_keeps_its_picture(auth_client, project, siblings):
    start(auth_client, project["id"], asset_key="a_flood", draft_spec=NO_BASE, make_picture=True)
    siblings.gen_jobs["job-1"].update(status="done", result_asset_ids=["pic-1"])
    siblings.fal_key = False
    listed = _list(auth_client, project["id"])[0]
    assert listed["status"] == "error" and listed["picture_id"] == "pic-1"
    assert listed["error"].startswith("The picture was made, but the clip couldn't be started")


def test_stopping_while_the_picture_is_made_starts_no_clip(auth_client, project, siblings):
    row = start(auth_client, project["id"], asset_key="a_flood", draft_spec=NO_BASE,
                make_picture=True).json()["data"]
    auth_client.delete(f"/api/generations/{row['id']}")
    siblings.gen_jobs["job-1"].update(status="done", result_asset_ids=["pic-1"])
    assert _list(auth_client, project["id"])[0]["status"] == "cancelled"
    assert len(siblings.generations) == 1
