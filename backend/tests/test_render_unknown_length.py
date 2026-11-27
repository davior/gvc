"""A clip whose file will not say how long it is (a browser recording).

Gecko Notes records in the browser, and a browser writes WebM as a live stream: no
duration, no index. A 30-minute recording was rendered as a tenth of a second, the
render said "Done", and the only trace was a warning about an overlay at 6:31 being
"before it starts".
"""

import subprocess
from pathlib import Path

import pytest

from app.gam.client import GamClient
from app.render import ffmpeg as F
from app.render import media as media_module
from app.render.compile import Placement, place_overlays
from app.render.media import MediaCache, resolve
from app.spec.validation import parse_spec
from tests.fake_siblings import gam_asset

needs_ffmpeg = pytest.mark.skipif(
    subprocess.run(["which", "ffprobe"], capture_output=True).returncode != 0,
    reason="ffmpeg/ffprobe not on PATH",
)


@pytest.fixture(scope="module")
def live_webm(tmp_path_factory) -> str:
    """Written to a pipe, as a recorder does: the muxer cannot go back and fill in a length."""
    path = tmp_path_factory.mktemp("live") / "recording.webm"
    with path.open("wb") as sink:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin",
             "-f", "lavfi", "-i", "testsrc=size=160x90:rate=25:d=6",
             "-f", "lavfi", "-i", "sine=d=6",
             "-c:v", "libvpx", "-b:v", "100k", "-c:a", "libvorbis", "-f", "webm", "pipe:1"],
            stdout=sink, check=True,
        )
    return str(path)


@needs_ffmpeg
def test_a_recording_with_no_header_duration_is_measured_from_its_packets(live_webm):
    assert F._header_duration(live_webm) == 0.0
    assert F.probe_duration(live_webm) == pytest.approx(6.0, abs=0.25)


def test_a_header_duration_that_is_absurd_for_the_file_size_is_replaced(tmp_path, monkeypatch):
    path = tmp_path / "x.webm"
    path.write_bytes(b"x" * 1000)
    monkeypatch.setattr(F, "IMPLAUSIBLE_BYTES_PER_SECOND", 10)
    monkeypatch.setattr(F, "_header_duration", lambda p: 8.0)
    monkeypatch.setattr(F, "_scan_duration", lambda p: 1800.0)
    assert F.probe_duration(str(path)) == 1800.0


def test_a_believable_header_is_not_scanned(tmp_path, monkeypatch):
    path = tmp_path / "x.mp4"
    path.write_bytes(b"x" * 1000)
    monkeypatch.setattr(F, "_header_duration", lambda p: 20.0)
    monkeypatch.setattr(F, "_scan_duration", lambda p: pytest.fail("no scan needed"))
    assert F.probe_duration(str(path)) == 20.0


# ─── resolving ──────────────────────────────────────────────────────────────────

CLIP = {
    "assets": {"cogwar": {"from": "gam", "id": "c", "type": "video", "label": "The Machine"}},
    "segments": [{"id": "s1", "kind": "clip", "visual": {"asset": "cogwar"}}],
}


def _resolve(tmp_path: Path, spec_json=CLIP):
    spec, issues = parse_spec(spec_json)
    assert spec is not None, issues
    gam = GamClient(None)
    try:
        return resolve(spec, gam, cache=MediaCache(tmp_path / "cache"), work_dir=str(tmp_path),
                       preview=False, frame=(1280, 720))
    finally:
        gam.close()


@pytest.fixture
def clip(siblings, files, monkeypatch):
    def make(library_duration):
        siblings.assets["c"] = gam_asset("c", "The Machine", "video", file_url="/media/c.bin",
                                         size_bytes=4, duration_seconds=library_duration)
        siblings.media_files = {"/media/c.bin": files["reel"]}
        # The file will not say how long it is.
        monkeypatch.setattr(media_module.F, "probe_duration", lambda path: 0.0)
        return siblings
    return make


def test_the_librarys_own_length_is_used_when_the_file_has_none(tmp_path, clip):
    clip(1800.0)
    resolved = _resolve(tmp_path)
    assert resolved.problems == []
    assert resolved.media["cogwar"].duration == 1800.0


def test_a_clip_of_unknown_length_stops_the_render_with_a_sentence(tmp_path, clip):
    clip(None)
    resolved = _resolve(tmp_path)
    assert len(resolved.problems) == 1
    assert "The Machine" in resolved.problems[0] and "how long" in resolved.problems[0]


def test_a_trim_with_an_out_point_says_how_long_it_plays(tmp_path, clip):
    clip(None)
    spec = {**CLIP, "segments": [{"id": "s1", "kind": "clip",
                                   "visual": {"asset": "cogwar", "trim": {"in": 0, "out": 30}}}]}
    assert _resolve(tmp_path, spec).problems == []


def test_a_looped_scene_does_not_need_a_length(tmp_path, clip):
    clip(None)
    spec = {**CLIP, "segments": [{"id": "s1", "kind": "scene", "visual": {"asset": "cogwar"}}]}
    assert _resolve(tmp_path, spec).problems == []


# ─── the warning ────────────────────────────────────────────────────────────────


def _overlay_warning(show, total=27.0):
    spec, issues = parse_spec({
        "assets": {},
        "segments": [{"id": "s1", "kind": "card", "label": "The Machine", "card": {"variant": "title", "title": "t"},
                      "overlays": [{"id": "o", "type": "text", "text": "hi", "show": show}]}],
    })
    assert spec is not None, issues
    warnings: list = []
    placed = place_overlays(spec, {}, Placement(segments={"s1": (0.0, total)}, beats={}, total=total),
                            warnings)
    return placed, warnings


def test_an_overlay_set_past_the_end_says_so_instead_of_blaming_its_anchors():
    placed, warnings = _overlay_warning({"from": {"edge": "start", "offset": 391},
                                         "to": {"edge": "start", "offset": 396}})
    assert placed == []
    [warning] = warnings
    assert "6:31" in warning and "0:27" in warning
    assert "ends before it starts" not in warning


def test_an_overlay_that_really_ends_before_it_starts_still_says_that():
    _, warnings = _overlay_warning({"from": {"edge": "start", "offset": 10},
                                    "to": {"edge": "start", "offset": 5}})
    assert any("ends before it starts" in w for w in warnings)
