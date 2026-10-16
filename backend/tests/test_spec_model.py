"""The VideoSpec itself: the worked example, the S1–S3 changes, migration."""

import pytest

from app.spec.model import VideoSpec, dump_spec
from app.spec.validation import parse_spec
from tests.conftest import load_fixture


def _valid(data):
    spec, issues = parse_spec(data)
    assert spec is not None, issues
    return spec


def _issues(data):
    spec, issues = parse_spec(data)
    assert spec is None, "expected the spec to be refused"
    return [(issue.path, issue.message) for issue in issues]


def _scene(**visual):
    return {
        "assets": {"a_map": {"from": "gam", "id": "g1", "type": "image"}},
        "segments": [{"id": "s1", "kind": "scene", "visual": {"asset": "a_map", **visual}}],
    }


# ── the documents the format was designed against ───────────────────────────

def test_the_notes_spec_doc_worked_example_validates_and_migrates():
    spec = _valid(load_fixture("salt_road_0_1.json"))
    assert spec.spec_version == "0.2"
    assert spec.source.kind == "note"
    # Two music beds that crossfade and a sound effect: the soundtrack changing through
    # the video is several tracks, nothing more.
    assert [t.id for t in spec.audio_tracks] == ["m_theme", "m_close", "x_bell"]


def test_a_spec_notes_importer_produced_validates_and_migrates():
    """Built by gecko-notes' own `import_note`, explicit nulls and all — what a push
    from Notes actually sends."""
    spec = _valid(load_fixture("notes_push_0_1.json"))
    assert spec.source.kind == "note"
    assert spec.source.note_id == "note-123"
    assert {ref.from_ for ref in spec.assets.values()} == {"notes"}


def test_dumping_writes_the_format_spelling_and_round_trips():
    spec = _valid(load_fixture("salt_road_0_1.json"))
    data = dump_spec(spec)
    caravan = next(s for s in data["segments"] if s["id"] == "s_caravan")
    assert caravan["visual"]["trim"] == {"in": 734.0, "out": 752.5}
    assert data["assets"]["a_map"]["from"] == "notes"
    assert "from_" not in str(data)
    assert dump_spec(VideoSpec.model_validate(data)) == data


def test_a_spec_from_a_newer_gvc_is_refused_by_name():
    assert _issues({"spec_version": "9.0"}) == [
        (["spec_version"], "spec_version '9.0' is not one this version of GVC can read "
                           "(it reads up to '0.2')")
    ]


def test_a_spec_without_a_version_is_taken_as_current():
    assert _valid({"title": "typed by hand"}).spec_version == "0.2"


# ── S1: Ken Burns framing ───────────────────────────────────────────────────

def test_a_path_moves_between_two_frames_of_the_picture():
    spec = _valid(_scene(motion={
        "effect": "path",
        "from": {"x": 0, "y": 0, "w": 1},
        "to": {"x": 0.05, "y": 0.6, "w": 0.3},
    }))
    motion = spec.segments[0].visual.motion
    assert motion.from_.w == 1 and motion.to.y == 0.6
    assert dump_spec(spec)["segments"][0]["visual"]["motion"]["from"] == {"x": 0, "y": 0, "w": 1}


@pytest.mark.parametrize("motion, path, fragment", [
    ({"effect": "path", "from": {"x": 0, "y": 0, "w": 1}},
     ["segments", 0, "visual", "motion"], 'needs both "from" and "to"'),
    ({"effect": "zoom_in", "to": {"x": 0, "y": 0, "w": 0.5}},
     ["segments", 0, "visual", "motion"], 'only read with effect "path"'),
    ({"effect": "path", "from": {"x": 0, "y": 0, "w": 1.4}, "to": {"x": 0, "y": 0, "w": 1}},
     ["segments", 0, "visual", "motion", "from", "w"], "less than or equal to 1"),
    ({"effect": "path", "from": {"x": 0.8, "y": 0, "w": 0.5}, "to": {"x": 0, "y": 0, "w": 1}},
     ["segments", 0, "visual", "motion", "from"], "right edge"),
    ({"effect": "alternate"}, [], '"alternate" only makes sense project-wide'),
])
def test_a_bad_frame_is_refused_with_its_path(motion, path, fragment):
    issues = _issues(_scene(motion=motion))
    assert any(p == path and fragment in m for p, m in issues), issues


def test_a_path_cannot_be_the_projects_default_move():
    issues = _issues({"style": {"motion": {
        "effect": "path", "from": {"x": 0, "y": 0, "w": 1}, "to": {"x": 0, "y": 0, "w": 0.5}}}})
    assert any("style.motion" in m for _, m in issues)


# ── S2: provenance ──────────────────────────────────────────────────────────

def test_a_brief_records_what_was_asked_for():
    spec = _valid({"source": {"kind": "brief", "prompt": "3 minutes on the salt road",
                              "asset_ids": ["g1"]}})
    assert spec.source.prompt.startswith("3 minutes")


def test_an_empty_0_1_source_is_dropped_rather_than_pointing_at_no_note():
    spec = _valid({"spec_version": "0.1", "source": {"note_id": None, "selection": False}})
    assert spec.source is None


# ── S3: search placeholders that resolve to a moment ────────────────────────

def test_a_search_can_ask_for_a_moment_and_resolve_to_one():
    spec = _valid({"assets": {"a_x": {
        "from": "search", "query": "people talking about water", "type": "video",
        "moment": {"min": 4, "max": 15},
        "status": "resolved", "result": {"from": "gam", "id": "g9", "in": 61.2, "out": 70.0},
    }}})
    result = spec.assets["a_x"].result
    assert (result.in_, result.out) == (61.2, 70.0)


def test_a_moment_whose_max_is_shorter_than_its_min_is_refused():
    issues = _issues({"assets": {"a_x": {
        "from": "search", "query": "q", "moment": {"min": 10, "max": 2}}}})
    assert issues == [(["assets", "a_x", "moment"], "moment.max is shorter than moment.min")]


# ── defaults cascade: transitions ───────────────────────────────────────────

def test_a_scene_overrides_only_the_transition_fields_it_names():
    spec = _valid({"segments": [{"id": "s1", "kind": "scene",
                                 "transition_in": {"style": "dissolve"}}]})
    override = spec.segments[0].transition_in
    assert override.style == "dissolve"
    # Left unset, so the project's duration applies rather than a restated default.
    assert override.duration is None


# ── limits live in the schema ───────────────────────────────────────────────

def test_an_out_of_range_value_is_refused_not_clamped():
    issues = _issues({"voice": {"speed": 3}})
    assert issues == [(["voice", "speed"], "Input should be less than or equal to 2")]


def test_structural_rules_still_hold():
    issues = _issues({"segments": [
        {"id": "s1", "kind": "scene", "visual": {"asset": "missing"}},
        {"id": "s1", "kind": "card"},
    ]})
    message = issues[0][1]
    assert "duplicate segment id 's1'" in message
    assert "unknown asset 'missing'" in message
    assert "is a card with no card" in message


def test_a_misspelt_field_is_an_error_not_ignored():
    issues = _issues({"segments": [{"id": "s1", "kind": "scene", "transtion_in": {}}]})
    assert issues == [(["segments", 0, "transtion_in"], "Extra inputs are not permitted")]
