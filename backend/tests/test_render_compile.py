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
    # The lower third is M2b, and says so rather than vanishing.
    assert any("lower_third" in w for w in warnings)


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
