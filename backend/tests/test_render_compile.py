"""The compile step: units, durations, layout and anchors, with no ffmpeg at all."""

import pytest

from app.render.compile import (
    Media, layout, place_tracks, placement, plan_units, resolve_anchor, unit_duration, Orphaned,
    beat_pause_ms, chapters,
)
from app.spec.validation import parse_spec
from tests.conftest import load_fixture

IMAGE = Media(path="img.png", kind="image", width=1600, height=900)
VIDEO = Media(path="reel.mp4", kind="video", duration=3600.0, has_audio=True)
SONG = Media(path="song.mp3", kind="audio", duration=200.0)


def spec_of(data):
    spec, issues = parse_spec(data)
    assert spec is not None, issues
    return spec


def salt_road():
    spec = spec_of(load_fixture("salt_road_0_1.json"))
    media = {key: IMAGE for key in spec.assets}
    media.update({"a_caravan": VIDEO, "a_intro": VIDEO, "a_outro": VIDEO,
                  "a_theme": SONG, "a_close": SONG, "a_bell": SONG})
    return spec, media


def test_a_scene_is_cut_at_its_quote_and_cards_and_clips_are_one_unit_each():
    spec, media = salt_road()
    warnings = []
    units = plan_units(spec, media, warnings)
    shape = [(u.segment_id, u.kind, [b.id for b in u.beats], u.panel.kind if u.panel else None)
             for u in units]
    assert shape == [
        ("s_title", "card", [], None),
        ("s_intro", "video_sound", [], None),
        ("s_open", "still", ["b1", "b2", "b3"], None),
        ("s_caravan", "video_muted", ["b1"], None),
        ("s_caravan", "video_muted", ["b2"], "quote"),
        ("s_caravan", "video_muted", ["b3"], None),
        ("s_market", "still", ["b1", "b2"], None),
        ("s_ruins", "still", ["b1", "b2"], None),
        ("s_outro", "video_sound", [], None),
    ]
    # The lower third doesn't cut the scene: it is drawn over the stitched video.
    assert warnings == []


def test_defaults_cascade_field_by_field():
    spec, media = salt_road()
    units = plan_units(spec, media, [])
    caravan = [u for u in units if u.segment_id == "s_caravan"]
    # Its own dissolve on the way in, at its own 1.0 s ...
    assert (caravan[0].transition_in.style, caravan[0].transition_in.duration) == ("dissolve", 1.0)
    # ... and the units it was cut into keep the segment's settings too.
    assert caravan[0].first_in_segment and not caravan[1].first_in_segment
    market = next(u for u in units if u.segment_id == "s_market")
    assert (market.transition_in.style, market.transition_in.duration) == ("fade", 0.6)
    assert market.motion.effect == "pan_right"
    opening = next(u for u in units if u.segment_id == "s_open")
    assert opening.motion.effect == "zoom_in" and opening.motion.amount == 0.08
    # The trim is taken in the file's seconds; the clip and intros keep their sound.
    assert caravan[0].trim == (734.0, 18.5)
    ruins = next(u for u in units if u.segment_id == "s_ruins")
    assert ruins.min_seconds == 8
    intro = next(u for u in units if u.segment_id == "s_intro")
    assert intro.chrome is False


def test_only_the_style_can_be_overridden_and_the_duration_still_inherited():
    spec = spec_of({
        "style": {"transition": {"style": "fade", "duration": 1.4}},
        "segments": [{"id": "a", "kind": "scene"},
                     {"id": "b", "kind": "scene", "transition_in": {"style": "dissolve"}}],
    })
    units = plan_units(spec, {}, [])
    assert (units[1].transition_in.style, units[1].transition_in.duration) == ("dissolve", 1.4)


def test_a_gam_clip_is_its_parents_file_from_its_in_point():
    clip = Media(path="parent.mp4", kind="video", duration=3600.0, offset=100.0, length=30.0)
    spec = spec_of({"assets": {"c": {"from": "gam", "id": "x"}},
                    "segments": [{"id": "s", "kind": "scene", "visual": {"asset": "c"}},
                                 {"id": "t", "kind": "scene",
                                  "visual": {"asset": "c", "trim": {"in": 5, "out": 9}}}]})
    first, second = plan_units(spec, {"c": clip}, [])
    assert first.trim == (100.0, 30.0)
    assert second.trim == (105.0, 4.0)


def test_alternate_cycles_through_the_presets():
    spec = spec_of({"style": {"motion": {"effect": "alternate"}},
                    "assets": {"i": {"from": "gam", "id": "x"}},
                    "segments": [{"id": f"s{n}", "kind": "scene", "visual": {"asset": "i"}}
                                 for n in range(4)]})
    units = plan_units(spec, {"i": IMAGE}, [])
    assert [u.motion.effect for u in units] == ["zoom_in", "pan_right", "zoom_out", "pan_left"]


def test_durations_floor_and_fix():
    spec, media = salt_road()
    units = plan_units(spec, media, [])
    card, intro = units[0], units[1]
    assert unit_duration(card, narration_seconds=0, cards_seconds=3.5) == 3.5
    assert unit_duration(intro, 0, 3.5) == 3600.0
    caravan = units[3]
    assert unit_duration(caravan, narration_seconds=1.0, cards_seconds=3.5) == 2.5
    assert unit_duration(caravan, narration_seconds=7.2, cards_seconds=3.5) == 7.2
    ruins = units[7]
    assert unit_duration(ruins, narration_seconds=5.0, cards_seconds=3.5) == 8


def _three(styles):
    spec = spec_of({"segments": [
        {"id": "a", "kind": "scene"},
        {"id": "b", "kind": "scene", "transition_in": {"style": styles[0], "duration": 1.0}},
        {"id": "c", "kind": "scene", "transition_in": {"style": styles[1], "duration": 1.0}},
    ]})
    return plan_units(spec, {}, [])


def test_each_join_has_its_own_transition_and_only_blends_overlap():
    units = _three(["dissolve", "fade"])
    timeline = layout(units, [10.0, 10.0, 10.0], [])
    assert timeline.joins[1].is_blend and timeline.joins[1].overlap == 1.0
    assert not timeline.joins[2].is_blend and timeline.joins[2].style == "fade"
    assert timeline.starts == [0.0, 9.0, 19.0]
    assert timeline.total == 29.0


def test_a_blend_never_covers_more_than_half_a_short_unit():
    units = _three(["dissolve", "none"])
    timeline = layout(units, [10.0, 1.0, 10.0], [])
    assert timeline.joins[1].overlap == 0.5
    assert timeline.joins[2].is_cut
    assert timeline.total == 20.5


def _clip_then(style):
    spec = spec_of({
        "assets": {"v": {"from": "gam", "id": "g1", "type": "video"}},
        "segments": [
            {"id": "a", "kind": "clip", "visual": {"asset": "v", "audio": "play",
                                                    "trim": {"in": 10, "out": 16}}},
            {"id": "b", "kind": "scene", "transition_in": {"style": style, "duration": 0.6}},
            {"id": "c", "kind": "scene", "transition_in": {"style": "dissolve",
                                                          "duration": 0.6}},
        ]})
    return plan_units(spec, {"v": VIDEO}, [])


def test_a_blend_out_of_a_clip_lengthens_it_rather_than_cutting_its_last_words():
    units = _clip_then("dissolve")
    durations = [6.0, 10.0, 10.0]
    timeline = layout(units, durations, [])
    assert units[0].tail == pytest.approx(0.6)
    assert timeline.durations[0] == pytest.approx(6.6)
    # The blend starts once the clip has reached its out point.
    assert timeline.starts[1] == pytest.approx(6.0)
    # A muted scene into a blend is overlapped as before.
    assert units[1].tail == 0.0 and timeline.durations[1] == 10.0
    assert timeline.starts[2] == pytest.approx(15.4)
    assert durations == [6.0, 10.0, 10.0]


def test_a_cut_out_of_a_clip_adds_nothing():
    units = _clip_then("none")
    timeline = layout(units, [6.0, 10.0, 10.0], [])
    assert units[0].tail == 0.0
    assert timeline.durations[0] == 6.0 and timeline.starts[1] == 6.0


def _placed():
    spec, media = salt_road()
    units = plan_units(spec, media, [])
    durations = [3.5, 5.0, 12.0, 6.0, 4.0, 5.0, 9.0, 8.0, 6.0]
    timeline = layout(units, durations, [])
    offsets = [{} for _ in units]
    offsets[6] = {"b1": (0.0, 4.0), "b2": (4.0, 9.0)}
    return spec, media, units, timeline, placement(units, timeline, offsets)


def test_the_worked_examples_crossfade_lands_on_the_cut_into_the_ruins():
    spec, media, units, timeline, where = _placed()
    warnings = []
    tracks = {p.track.id: p for p in place_tracks(spec, media, where, warnings)}
    ruins_start = where.segments["s_ruins"][0]
    market_end = where.segments["s_market"][1]

    theme, close, bell = tracks["m_theme"], tracks["m_close"], tracks["x_bell"]
    assert theme.start == where.segments["s_open"][0]
    assert theme.start + theme.length == pytest.approx(market_end)
    # The closing theme starts three seconds before the ruins and fades in over them:
    # the two beds overlap, which is the crossfade.
    assert close.start == pytest.approx(ruins_start - 3.0)
    assert close.start < theme.start + theme.length
    assert close.trim_in == 12.0
    assert theme.loop and theme.duck
    # The bell lands 0.3 s before its line, and plays once, unducked.
    assert bell.start == pytest.approx(where.beats[("s_market", "b1")][0] - 0.3)
    assert not bell.loop and not bell.duck
    # Once, to its natural end, or the video's if that comes first.
    assert bell.length == pytest.approx(min(200.0, where.total - bell.start))
    assert warnings == []


def test_an_anchor_to_a_removed_segment_drops_its_track_with_a_warning():
    spec, media, units, timeline, where = _placed()
    spec.segments = [s for s in spec.segments if s.id != "s_market"]
    del where.segments["s_market"]
    warnings = []
    placed = place_tracks(spec, media, where, warnings)
    assert "m_theme" not in [p.track.id for p in placed]
    assert any("m_theme" in w and "s_market" in w for w in warnings)


def test_anchor_offsets_are_held_inside_the_video():
    spec, media, units, timeline, where = _placed()
    from app.spec.model import AnchorRef
    assert resolve_anchor(AnchorRef(segment="s_title", edge="start", offset=-5), where) == 0.0
    assert resolve_anchor("video_end", where) == where.total
    with pytest.raises(Orphaned):
        resolve_anchor(AnchorRef(segment="gone", edge="end"), where)


def test_chapter_marks_follow_the_units():
    spec, media, units, timeline, where = _placed()
    marks = chapters(units, timeline)
    assert [m[2] for m in marks] == ["The Salt Road", "Intro", "Where it started", "The caravans",
                                     "The market", "What remains", "Outro"]
    assert marks[-1][1] == timeline.total
    assert all(a[1] == b[0] for a, b in zip(marks, marks[1:]))


def test_pauses_after_beats():
    spec, media = salt_road()
    beats = spec.segments[2].beats
    assert beat_pause_ms(spec, beats, 0) == 800   # a heading
    assert beat_pause_ms(spec, beats, 1) == 350   # between paragraphs
    assert beat_pause_ms(spec, beats, 2) == 600   # the end of the scene


# ── M2b: timed overlays and credits ─────────────────────────────────────────

from app.render.compile import CREDIT_LINES_PER_CARD, credits_units, place_overlays  # noqa: E402
from app.render.credits import credit_lines, description_text  # noqa: E402
from app.render import ffmpeg as F  # noqa: E402
from app.render.options import RenderOptions  # noqa: E402
from app.spec.model import AnchorRef, Span, TextOverlay  # noqa: E402


def _with_overlays(*overlays):
    spec, media, units, timeline, where = _placed()
    market = next(s for s in spec.segments if s.id == "s_market")
    market.overlays = list(overlays)
    return spec, media, where


def test_an_overlay_with_no_span_covers_its_scene_with_a_default_fade():
    spec, media, where = _with_overlays(TextOverlay(id="o", type="text", text="Hi"))
    [placed] = [p for p in place_overlays(spec, media, where, []) if p.overlay.id == "o"]
    assert (placed.start, placed.end) == where.segments["s_market"]
    assert placed.fade == 0.3


def test_overlay_anchors_default_to_their_own_scene_and_may_reach_into_the_next():
    span = Span.model_validate({"from": {"edge": "start", "offset": 0.5},
                                "to": {"segment": "s_ruins", "edge": "start", "offset": 1.0}})
    beat = Span.model_validate({"from": {"beat": "b1", "edge": "start"},
                                "to": {"beat": "b1", "edge": "end"}})
    spec, media, where = _with_overlays(
        TextOverlay(id="o1", type="text", text="Hi", show=span),
        TextOverlay(id="o2", type="text", text="Hi", show=beat, fade=5),
    )
    placed = {p.overlay.id: p for p in place_overlays(spec, media, where, [])}
    assert placed["o1"].start == pytest.approx(where.segments["s_market"][0] + 0.5)
    assert placed["o1"].end == pytest.approx(where.segments["s_ruins"][0] + 1.0)
    assert (placed["o2"].start, placed["o2"].end) == where.beats[("s_market", "b1")]
    # A fade longer than half the window is held to half, so in and out never cross.
    assert placed["o2"].fade == pytest.approx(2.0)


def test_an_overlay_that_cannot_be_placed_is_dropped_with_a_warning():
    orphan = Span.model_validate({"from": {"edge": "start"},
                                  "to": {"segment": "gone", "edge": "end"}})
    backwards = Span.model_validate({"from": {"edge": "end"}, "to": {"edge": "start"}})
    spec, media, where = _with_overlays(
        TextOverlay(id="o1", type="text", text="a", show=orphan),
        TextOverlay(id="o2", type="text", text="b", show=backwards),
    )
    warnings = []
    placed = place_overlays(spec, media, where, warnings)
    assert not [p for p in placed if p.overlay.id in ("o1", "o2")]
    assert any("'gone'" in w for w in warnings)
    assert any("ends before it starts" in w for w in warnings)


def test_an_image_overlay_needs_a_picture():
    from app.spec.model import ImageOverlay
    spec, media, where = _with_overlays(ImageOverlay(id="o", type="image", asset="a_theme"))
    warnings = []
    assert not [p for p in place_overlays(spec, media, where, warnings) if p.overlay.id == "o"]
    assert any("needs a picture" in w for w in warnings)


def test_credit_lines_follow_first_use_and_are_said_once():
    spec, _ = salt_road()
    assert credit_lines(spec, {}) == []          # no `credits`: none
    spec = spec.model_copy(update={"credits": None})
    from app.spec.model import Credits
    spec.credits = Credits(extra=["  Narrated by Rex "])
    keys = [s.visual.asset for s in spec.segments if s.visual]
    credits = {keys[0]: "Footage: A", keys[1]: "Photo: B", keys[2]: "Footage: A"}
    assert credit_lines(spec, credits) == ["Footage: A", "Photo: B", "Narrated by Rex"]
    spec.credits = Credits(auto=False, extra=["Narrated by Rex"])
    assert credit_lines(spec, credits) == ["Narrated by Rex"]


def test_long_credits_run_over_several_cards_and_none_without_lines():
    spec, _ = salt_road()
    from app.spec.model import Credits
    spec.credits = Credits()
    assert credits_units(spec, []) == []
    lines = [f"Line {i}" for i in range(CREDIT_LINES_PER_CARD + 3)]
    cards = credits_units(spec, lines)
    assert [len(u.credits) for u in cards] == [CREDIT_LINES_PER_CARD, 3]
    assert all(u.kind == "card" and not u.chrome for u in cards)
    spec.credits = Credits(card=False)
    assert credits_units(spec, lines) == []


def test_the_description_lists_chapters_from_zero_then_credits():
    spec, _ = salt_road()
    from app.spec.model import Credits
    spec.credits = Credits()
    spec.output.chapters = True
    text = description_text(spec, ["Photo: B"], [(4.0, 70.0, "Market"), (70.0, 200.0, "Ruins")])
    assert text == f"0:00 {spec.title}\n0:04 Market\n1:10 Ruins\n\nCredits\nPhoto: B"
    spec.credits = Credits(description=False)
    spec.output.chapters = False
    assert description_text(spec, ["Photo: B"], [(0.0, 10.0, "x")]) == ""


def test_the_overlay_pass_draws_each_layer_only_in_its_window_and_copies_the_sound():
    argv = F.build_overlay_pass(
        "stitched.mp4",
        [F.TimedLayer("a.png", 1.0, 4.5, 0.3), F.TimedLayer("b.png", 2.0, 3.0, 0.0)],
        "out.mp4", options=RenderOptions(), preview=True, duration=10.0)
    graph = argv[argv.index("-filter_complex") + 1]
    assert "fade=t=in:st=1.000:d=0.300:alpha=1" in graph
    assert "fade=t=out:st=4.200:d=0.300:alpha=1" in graph
    assert "enable='between(t,1.000,4.500)'" in graph
    assert "enable='between(t,2.000,3.000)'" in graph
    assert "[l2]" in graph and "fade" not in graph.split("[1:v]")[0]
    assert argv[argv.index("-c:a") + 1] == "copy"
    assert argv.count("-c:a") == 1 and argv[argv.index("-map") + 1] == "[v2]"
