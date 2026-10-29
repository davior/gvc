"""Rendering a GAM video from the version that best matches the output (gam#56)."""

from pathlib import Path

import pytest

from app.gam.client import GamClient
from app.render.media import MediaCache, fills_frame, pick_source, resolve
from app.schemas_gam import GamAssetRead, GamVersion
from app.spec.validation import parse_spec
from tests.fake_siblings import gam_asset

FHD = (1920, 1080)
VERTICAL_FHD = (1080, 1920)
PREVIEW = (854, 480)


def _asset(width=3840, height=2160) -> GamAssetRead:
    return GamAssetRead(id="r", name="reel", asset_type="video", width=width, height=height,
                        file_url="https://gam.test/media/r.mp4", size_bytes=4000)


def _version(short_side: int, width: int, height: int) -> GamVersion:
    return GamVersion(id=f"v{short_side}", short_side=short_side, width=width, height=height,
                      size_bytes=short_side, file_url=f"https://gam.test/media/r{short_side}.mp4")


LADDER = [_version(1440, 2560, 1440), _version(1080, 1920, 1080),
          _version(720, 1280, 720), _version(480, 854, 480)]


# ─── choosing ──────────────────────────────────────────────────────────────────


def test_a_1080p_render_of_a_4k_original_reads_its_1080p():
    picked = pick_source(_asset(), "r", LADDER, FHD, fill=False)
    assert (picked.short_side, picked.cache_id) == (1080, "r@1080")


def test_a_preview_reads_the_smallest_that_is_still_sharp():
    assert pick_source(_asset(), "r", LADDER, PREVIEW, fill=False).short_side == 480


def test_the_next_size_up_when_the_exact_one_is_not_made():
    ladder = [v for v in LADDER if v.short_side != 1080]
    assert pick_source(_asset(), "r", ladder, FHD, fill=False).short_side == 1440


def test_the_original_when_no_version_is_big_enough():
    small = [_version(720, 1280, 720)]
    picked = pick_source(_asset(), "r", small, FHD, fill=False)
    assert picked.short_side is None
    assert picked.cache_id == "r"


def test_the_original_when_there_are_no_versions():
    assert pick_source(_asset(), "r", [], FHD, fill=False).short_side is None


def test_a_landscape_video_cropped_into_a_vertical_frame_needs_its_height_to_fill():
    # Cropping 16:9 into 9:16 shows it 1920 tall, so the 1080p version (1080 tall) is
    # not enough; 1440 is not either; only the original's 2160 is.
    assert pick_source(_asset(), "r", LADDER, VERTICAL_FHD, fill=True).short_side is None
    # Fitted inside the same frame instead, it is shown 1080 wide, and the 720p is
    # 1280 wide: enough.
    assert pick_source(_asset(), "r", LADDER, VERTICAL_FHD, fill=False).short_side == 720


def test_a_version_rounded_a_pixel_short_still_counts():
    # A 1002x750 original's 1080p version is 1442x1080; a 4:3 picture in a 16:9 frame
    # is limited by its height, which is exactly enough.
    asset = _asset(width=2004, height=1500)
    picked = pick_source(asset, "r", [_version(1080, 1442, 1080)], FHD, fill=False)
    assert picked.short_side == 1080


def test_an_original_of_unknown_size_is_used_as_it_is():
    assert pick_source(_asset(width=None, height=None), "r", LADDER, FHD, fill=False).short_side is None


def test_a_crop_anywhere_makes_the_asset_fill():
    spec, issues = parse_spec({
        "assets": {"a_reel": {"from": "gam", "id": "r", "type": "video"}},
        "segments": [
            {"id": "s1", "kind": "scene", "visual": {"asset": "a_reel"}},
            {"id": "s2", "kind": "scene", "visual": {"asset": "a_reel", "fit": "crop"}},
        ],
    })
    assert spec is not None, issues
    assert fills_frame(spec, "a_reel") is True

    spec.segments[1].visual.fit = None
    assert fills_frame(spec, "a_reel") is False
    spec.style.fit = "crop"
    assert fills_frame(spec, "a_reel") is True


# ─── resolving, against the fake GAM ────────────────────────────────────────────


SPEC = {
    "assets": {"a_reel": {"from": "gam", "id": "r", "type": "video"}},
    "segments": [{"id": "s1", "kind": "scene", "visual": {"asset": "a_reel"}}],
}


def _resolve(tmp_path: Path, frame: tuple):
    spec, issues = parse_spec(SPEC)
    assert spec is not None, issues
    gam = GamClient(None)
    try:
        return resolve(spec, gam, cache=MediaCache(tmp_path / "cache"), work_dir=str(tmp_path),
                       preview=False, frame=frame)
    finally:
        gam.close()


@pytest.fixture
def reel(siblings, files):
    siblings.assets["r"] = gam_asset("r", "reel", "video", width=3840, height=2160,
                                     file_url="/media/r.bin", size_bytes=4)
    siblings.media_files = {"/media/r.bin": files["reel"], "/media/r1080.bin": files["reel"]}
    return siblings


def _media_fetched(siblings) -> list:
    return [r.url.path for r in siblings.requests if r.url.path.startswith("/media/")]


def test_the_render_fetches_the_matching_version(tmp_path, reel):
    reel.versions["r"] = [{"id": "v1", "short_side": 1080, "width": 1920, "height": 1080,
                           "size_bytes": 2, "file_url": "/media/r1080.bin"}]

    resolved = _resolve(tmp_path, FHD)

    assert resolved.problems == []
    assert _media_fetched(reel) == ["/media/r1080.bin"]
    assert Path(resolved.media["a_reel"].path).name == "r@1080"


def test_a_gam_without_versions_renders_the_original(tmp_path, reel):
    # No entry: the fake answers 404, as a GAM older than gam#56 does.
    resolved = _resolve(tmp_path, FHD)

    assert resolved.problems == []
    assert _media_fetched(reel) == ["/media/r.bin"]


def test_an_original_over_the_size_limit_renders_from_a_version_that_fits(
    tmp_path, reel, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "render_max_file_mb", 1)
    reel.assets["r"]["size_bytes"] = 5 * 1024 * 1024
    reel.versions["r"] = [{"id": "v1", "short_side": 1080, "width": 1920, "height": 1080,
                           "size_bytes": 2, "file_url": "/media/r1080.bin"}]

    resolved = _resolve(tmp_path, FHD)

    assert resolved.problems == []
    assert _media_fetched(reel) == ["/media/r1080.bin"]


def test_a_version_over_the_size_limit_is_refused_before_it_downloads(
    tmp_path, reel, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "render_max_file_mb", 1)
    reel.versions["r"] = [{"id": "v1", "short_side": 1080, "width": 1920, "height": 1080,
                           "size_bytes": 5 * 1024 * 1024, "file_url": "/media/r1080.bin"}]

    resolved = _resolve(tmp_path, FHD)

    assert len(resolved.problems) == 1 and "reel" in resolved.problems[0]
    assert _media_fetched(reel) == []
