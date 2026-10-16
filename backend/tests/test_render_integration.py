"""A real render, through real ffmpeg, of a small video with everything M2 adds.

GAM and Notes are faked (`fake_siblings.py`): GAM serves generated files, and Notes'
speech answers every chunk with a tone of known length. Rendered at preview size.
"""

import json
import os
import subprocess

import pytest

from app.gam.client import GamClient
from app.render import ffmpeg as F
from app.render.renderer import RenderRefused, render
from app.render.tts import NotesSpeech, SpeechError
from app.spec.validation import parse_spec

pytestmark = pytest.mark.skipif(not F.ffmpeg_available(), reason="needs ffmpeg")


SPEC = {
    "title": "Water Wars",
    "output": {"chapters": True, "subtitles": "sidecar"},
    "style": {"transition": {"style": "fade", "duration": 0.4}},
    "assets": {
        "a_pic": {"from": "gam", "id": "p", "type": "image"},
        "a_reel": {"from": "gam", "id": "r", "type": "video"},
        "a_song1": {"from": "gam", "id": "a", "type": "audio"},
        "a_song2": {"from": "gam", "id": "b", "type": "audio"},
    },
    "segments": [
        {"id": "s_title", "kind": "card", "role": "title", "chapter": "Start",
         "card": {"variant": "title", "title": "Water Wars"}},
        {"id": "s_valley", "kind": "scene", "chapter": "The valley",
         "visual": {"asset": "a_pic", "motion": {
             "effect": "path", "from": {"x": 0, "y": 0, "w": 1}, "to": {"x": 0.5, "y": 0.4, "w": 0.4}}},
         "narration": {"beats": [{"id": "b1", "text": "The valley used to run clear."},
                                 {"id": "b2", "text": "Now every drop is fought over."}]}},
        {"id": "s_river", "kind": "scene", "chapter": "The river",
         "transition_in": {"style": "dissolve", "duration": 1.0},
         "visual": {"asset": "a_reel", "trim": {"in": 5, "out": 9}},
         "narration": {"beats": [{"id": "b1", "text": "The river is lower every year."}]}},
        {"id": "s_voice", "kind": "clip",
         "visual": {"asset": "a_reel", "trim": {"in": 2, "out": 5}, "audio": "play"}},
    ],
    "audio_tracks": [
        {"id": "m_one", "asset": "a_song1",
         "start": {"segment": "s_valley", "edge": "start"},
         "end": {"segment": "s_river", "edge": "start", "offset": 1.0}, "fade_out": 1.0},
        {"id": "m_two", "asset": "a_song2",
         "start": {"segment": "s_river", "edge": "start", "offset": -1.0},
         "end": "video_end", "fade_in": 1.0},
    ],
}


def _render(tmp_path, spec_data, preview=True):
    spec, issues = parse_spec(spec_data)
    assert spec is not None, issues
    gam, speech = GamClient(None), NotesSpeech(None)
    stages = []
    try:
        return render(
            spec=spec, preview=preview, work_dir=str(tmp_path / "work"),
            out_dir=str(tmp_path / "out"), data_dir=str(tmp_path / "data"), user_id="u",
            gam=gam, speech=speech, progress=lambda s, p, d: stages.append((s, p)),
            max_segments=200, max_narration_chars=10_000,
        ), speech
    finally:
        gam.close()
        speech.close()


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_chapters",
                          "-show_format", "-of", "json", path], capture_output=True, check=True)
    return json.loads(out.stdout)


def test_a_video_with_a_path_a_dissolve_a_clip_and_two_crossfading_tracks(tmp_path, library):
    result, speech = _render(tmp_path, SPEC)

    info = _probe(result.video)
    # MP4 carries chapter marks as a `data` stream of their own.
    kinds = sorted(s["codec_type"] for s in info["streams"] if s["codec_type"] != "data")
    assert kinds == ["audio", "video"]
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (854, 480)
    # Card (3.5) + valley (two 1.5 s beats + pauses) + river (2.5 floor or narration)
    # + the 3 s clip, minus the 1 s dissolve: about 13-15 s. The exact figure is the
    # compiler's; what matters here is that the stitched file agrees with it.
    assert 11.0 < result.duration < 17.0
    assert float(info["format"]["duration"]) == pytest.approx(result.duration, abs=0.25)
    assert [c["tags"]["title"] for c in info["chapters"]] == ["Start", "The valley", "The river"]
    assert result.subtitles and os.path.getsize(result.subtitles) > 0
    assert result.poster and os.path.exists(result.poster)
    assert result.warnings == []

    # Every chunk but the first was read with the engine Notes pinned on the first.
    assert speech.provider == "deepgram"
    assert library.spoken[0]["provider"] == "auto"
    assert all(s["provider"] == "deepgram" for s in library.spoken[1:])
    assert len(library.spoken) == 3

    # The media cache: a second render fetches nothing from GAM's media again.
    fetched = [r for r in library.requests if r.url.path.startswith("/media/")]
    assert len(fetched) == 4
    library.requests.clear()
    again, _ = _render(tmp_path, SPEC)
    assert not [r for r in library.requests if r.url.path.startswith("/media/")]
    assert again.duration == pytest.approx(result.duration, abs=0.05)


def test_a_full_render_refuses_placeholders_and_note_files_and_says_which(tmp_path, library):
    data = json.loads(json.dumps(SPEC))
    data["assets"]["a_find"] = {"from": "search", "query": "a dry riverbed"}
    data["assets"]["a_note"] = {"from": "notes", "url": "/media/u/x.png", "type": "image",
                                "label": "the old map"}
    data["segments"][1]["visual"] = {"asset": "a_find"}
    data["segments"].append({"id": "s_map", "kind": "scene", "visual": {"asset": "a_note"}})
    with pytest.raises(RenderRefused) as refused:
        _render(tmp_path, data, preview=False)
    message = str(refused.value)
    assert "a dry riverbed" in message and "the old map" in message


def test_a_preview_draws_a_placeholder_as_a_slate(tmp_path, library):
    data = json.loads(json.dumps(SPEC))
    data["assets"]["a_find"] = {"from": "search", "query": "a dry riverbed"}
    data["segments"][1]["visual"] = {"asset": "a_find"}
    result, _ = _render(tmp_path, data, preview=True)
    assert os.path.exists(result.video)


def test_a_notes_too_old_to_pin_the_voice_stops_the_render(tmp_path, library):
    library.speech_provider = None
    with pytest.raises(SpeechError) as stopped:
        _render(tmp_path, SPEC)
    assert "gecko-notes#211" in str(stopped.value)


# ── M2b: timed overlays and credits ─────────────────────────────────────────

OVERLAID = {
    "title": "Overlays",
    "output": {"chapters": True, "subtitles": "off"},
    "style": {"background": {"type": "solid", "colors": ["#000000"]},
              "transition": {"style": "none", "duration": 0.5}, "cards": {"seconds": 2.0}},
    "segments": [
        {"id": "s_one", "kind": "scene", "chapter": "One", "duration": {"fixed": 4.0},
         "overlays": [
             # Held across the dissolve into s_two: only the overlay pass can draw that.
             {"id": "o_text", "type": "text", "text": "ACROSS", "size_pct": 20,
              "fade": 0,
              "show": {"from": {"edge": "start", "offset": 1.0},
                       "to": {"segment": "s_two", "edge": "start", "offset": 1.5}}},
             {"id": "o_name", "type": "lower_third", "title": "Ada Lovelace",
              "subtitle": "Mathematician", "fade": 0,
              "show": {"from": {"edge": "start", "offset": 0.5},
                       "to": {"edge": "start", "offset": 2.0}}},
         ]},
        {"id": "s_two", "kind": "scene", "chapter": "Two", "duration": {"fixed": 4.0},
         "transition_in": {"style": "dissolve", "duration": 1.0}},
    ],
    "credits": {"auto": True, "card": True, "description": True,
                "extra": ["Made with Gecko Video Creator"]},
}


def _luma(video, at, box):
    """Mean brightness (0-255) of a box (x0, y0, x1, y1, as fractions) at a time."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    width, height = 854, 480
    x0, y0, x1, y1 = (int(box[0] * width), int(box[1] * height),
                      int(box[2] * width), int(box[3] * height))
    total = count = 0
    for y in range(y0, y1):
        row = raw[y * width:(y + 1) * width]
        total += sum(row[x0:x1])
        count += x1 - x0
    return total / max(1, count)


CENTRE = (0.2, 0.4, 0.8, 0.6)
LOWER_LEFT = (0.03, 0.72, 0.4, 0.92)


def test_timed_overlays_show_only_between_their_anchors(tmp_path, library):
    result, _ = _render(tmp_path, OVERLAID)
    # s_one 0-4, s_two from 3 (the 1 s dissolve), then the 2 s credits card.
    assert result.duration == pytest.approx(4.0 + 4.0 - 1.0 + 2.0, abs=0.25)
    assert result.warnings == []

    # The text: on from 1.0 until 1.5 s into s_two (3.0 + 1.5 = 4.5), across the join.
    assert _luma(result.video, 0.5, CENTRE) < 5
    assert _luma(result.video, 2.0, CENTRE) > 20
    assert _luma(result.video, 3.5, CENTRE) > 20     # inside the dissolve
    assert _luma(result.video, 4.2, CENTRE) > 20     # into s_two
    assert _luma(result.video, 5.5, CENTRE) < 5

    # The lower third: 0.5 to 2.0 s, bottom left.
    assert _luma(result.video, 0.2, LOWER_LEFT) < 5
    assert _luma(result.video, 1.2, LOWER_LEFT) > 15
    assert _luma(result.video, 3.0, LOWER_LEFT) < 5


def test_credits_become_an_end_card_and_a_description(tmp_path, library):
    data = json.loads(json.dumps(SPEC))
    library.assets["p"]["credit"] = "Photo: Jane Doe / CC BY 4.0"
    library.assets["r"]["credit"] = "Footage: River Archive"
    library.assets["a"]["credit"] = "Photo: Jane Doe / CC BY 4.0"   # said once
    data["credits"] = {"extra": ["Narrated by Rex"]}
    plain, _ = _render(tmp_path / "plain", SPEC)
    result, _ = _render(tmp_path / "credited", data)

    # The card joins with the project's fade, so it adds its own length and no overlap.
    card = parse_spec(data)[0].style.cards.seconds
    assert result.duration == pytest.approx(plain.duration + card, abs=0.3)
    chapters, credits = result.description.split("\n\n")
    assert [line.split(" ", 1)[1] for line in chapters.split("\n")] == [
        "Start", "The valley", "The river"]
    assert chapters.startswith("0:00 ")
    assert credits == ("Credits\nPhoto: Jane Doe / CC BY 4.0\nFootage: River Archive\n"
                       "Narrated by Rex")
