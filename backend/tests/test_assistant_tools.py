"""The assistant's operations on a working copy of a spec: pure, with GAM faked."""

import pytest

from app.assistant import tools as T
from app.assistant.tools import Working
from app.gam.client import GamClient
from app.providers.base import ToolCall
from tests.fake_siblings import gam_asset, hit


def spec():
    return {
        "title": "Water Wars",
        "assets": {"a_map": {"from": "gam", "id": "p", "type": "image", "label": "Map"}},
        "segments": [
            {"id": "s_title", "kind": "card", "label": "Title",
             "card": {"variant": "title", "title": "Water Wars"}},
            {"id": "s_valley", "kind": "scene", "label": "The valley",
             "visual": {"asset": "a_map"},
             "narration": {"beats": [{"id": "b1", "text": "The valley used to run clear."}]}},
        ],
        "audio_tracks": [
            {"id": "m_theme", "asset": "a_map", "start": {"segment": "s_valley", "edge": "start"}},
        ],
    }


def run(w, name, **arguments):
    return T.execute(w, ToolCall(id="x", name=name, arguments=arguments))


def test_a_valid_spec_stays_valid_and_a_breaking_edit_is_refused_untouched():
    w = Working(spec())
    before = w.data
    result = run(w, "update_segment", segment_id="s_valley",
                 changes={"transition_in": {"style": "sideways"}})
    assert result.is_error and "transition_in" in result.content
    assert w.data == before and w.changes == []

    result = run(w, "update_segment", segment_id="s_valley",
                 changes={"transition_in": {"style": "dissolve"}, "chapter": "The valley"})
    assert not result.is_error
    assert w.data["segments"][1]["transition_in"] == {"style": "dissolve"}
    assert w.changes == ["Changed The valley: chapter, transition_in"]


def test_segments_are_addressed_by_id_and_unknown_ids_say_what_exists():
    w = Working(spec())
    result = run(w, "update_segment", segment_id="s_nope", changes={"label": "x"})
    assert result.is_error and "s_title, s_valley" in result.content

    run(w, "add_segment", after="s_title",
        segment={"id": "s_title", "kind": "scene", "label": "Dam",
                 "narration": {"beats": [{"id": "b1", "text": "Then came the dam."}]}})
    # A taken id is replaced, never duplicated.
    assert [s["id"] for s in w.data["segments"]] == ["s_title", "s_3", "s_valley"]
    run(w, "move_segment", segment_id="s_3", after="s_valley")
    assert [s["id"] for s in w.data["segments"]] == ["s_title", "s_valley", "s_3"]


def test_a_merge_patch_removes_with_null_and_replaces_lists_whole():
    w = Working(spec())
    run(w, "update_segment", segment_id="s_valley", changes={
        "visual": {"motion": {"effect": "zoom_in"}},
        "narration": {"beats": [{"id": "b1", "text": "One."}, {"id": "b2", "text": "Two."}]}})
    segment = w.data["segments"][1]
    assert segment["visual"] == {"asset": "a_map", "motion": {"effect": "zoom_in"}}
    assert [b["id"] for b in segment["narration"]["beats"]] == ["b1", "b2"]
    run(w, "update_segment", segment_id="s_valley", changes={"visual": {"motion": None}})
    assert "motion" not in w.data["segments"][1]["visual"]


def test_removing_a_segment_says_what_was_anchored_to_it():
    w = Working(spec())
    result = run(w, "remove_segment", segment_id="s_valley")
    assert not result.is_error
    assert "audio track m_theme" in result.content


def test_a_draft_with_mistakes_is_kept_and_repaired_edit_by_edit():
    w = Working(spec())
    draft = spec()
    draft["segments"][1]["transition_in"] = {"style": "sideways"}
    result = run(w, "replace_spec", spec=draft)
    assert not result.is_error and "1 issue to fix" in result.content and not w.valid
    # While issues remain, an edit is accepted and says what is left.
    result = run(w, "update_segment", segment_id="s_valley", changes={"label": "Valley"})
    assert "still has issues" in result.content
    result = run(w, "update_segment", segment_id="s_valley",
                 changes={"transition_in": {"style": "dissolve"}})
    assert w.valid and result.content.startswith("Done")


def test_the_project_id_survives_a_replaced_draft():
    data = spec()
    data["id"] = "proj-1"
    w = Working(data)
    run(w, "replace_spec", spec={**spec(), "id": "someone-else"})
    assert w.data["id"] == "proj-1"


@pytest.fixture
def gam(siblings):
    reel = gam_asset("r", "River interview", "video", duration_seconds=600.0,
                     credit="Footage: River Archive")
    siblings.assets["r"] = reel
    siblings.hits = [hit(reel, start=42.0, end=47.5, snippet="the «water» is gone")]
    client = GamClient("user-token")
    yield client
    client.close()


def test_a_search_hit_becomes_the_visual_with_its_moment_as_the_trim(gam, siblings):
    w = Working(spec(), gam=gam)
    found = run(w, "search_assets", query="people talking about water", type="video")
    assert '"said_at":[42.0,47.5]' in found.content and "River Archive" in found.content
    assert siblings.gam_requests()[0].headers["authorization"] == "Bearer user-token"

    result = run(w, "set_visual", segment_id="s_valley", gam_id="r")
    assert not result.is_error
    visual = w.data["segments"][1]["visual"]
    assert visual == {"asset": "a_river_interview", "trim": {"in": 41.5, "out": 48.0}}
    assert w.data["assets"]["a_river_interview"] == {
        "from": "gam", "id": "r", "type": "video", "label": "River interview"}


def test_an_empty_search_says_to_try_again_or_leave_a_placeholder(gam, siblings):
    siblings.hits = []
    w = Working(spec(), gam=gam)
    assert "add_placeholder" in run(w, "search_assets", query="glaciers").content
    result = run(w, "add_placeholder", segment_id="s_valley", kind="search",
                 text="a melting glacier", moment_min=4)
    assert not result.is_error
    key = w.data["segments"][1]["visual"]["asset"]
    assert w.data["assets"][key] == {"from": "search", "query": "a melting glacier",
                                     "type": "video", "moment": {"min": 4}}


def test_overlays_and_tracks_by_id(gam):
    w = Working(spec(), gam=gam)
    run(w, "search_assets", query="river")
    run(w, "add_overlay", segment_id="s_valley",
        overlay={"type": "lower_third", "title": "Ada", "subtitle": "Hydrologist"})
    [overlay] = w.data["segments"][1]["overlays"]
    run(w, "update_overlay", segment_id="s_valley", overlay_id=overlay["id"],
        changes={"show": {"from": {"edge": "start", "offset": 0.5}, "to": {"edge": "end"}}})
    assert w.data["segments"][1]["overlays"][0]["show"]["from"]["offset"] == 0.5
    run(w, "add_audio_track", gam_id="r", track={
        "kind": "sfx", "start": {"segment": "s_valley", "beat": "b1", "edge": "start"}})
    track = w.data["audio_tracks"][-1]
    assert track["id"].startswith("x_") and w.data["assets"][track["asset"]]["id"] == "r"
    run(w, "update_audio_track", track_id=track["id"], changes={"volume": 0.5})
    run(w, "remove_audio_track", track_id="m_theme")
    assert [t["id"] for t in w.data["audio_tracks"]] == [track["id"]]
    assert w.valid


def test_project_settings_only_through_set_project():
    w = Working(spec())
    result = run(w, "set_project", changes={"segments": []})
    assert result.is_error and "Segments and tracks" in result.content
    run(w, "set_project", changes={"style": {"transition": {"style": "dissolve"}},
                                   "credits": {"extra": ["Narrated by Rex"]}})
    assert w.data["style"]["transition"] == {"style": "dissolve"}
    assert w.valid


def test_bad_calls_come_back_as_errors_never_exceptions():
    w = Working(spec())
    assert run(w, "no_such_tool").is_error
    assert run(w, "update_segment", segment_id="s_valley").is_error   # missing argument
    unreadable = T.execute(w, ToolCall(id="x", name="get_spec", arguments={},
                                       parse_error="not JSON"))
    assert unreadable.is_error and "not JSON" in unreadable.content


def test_estimate_reads_the_working_copy():
    w = Working(spec())
    result = run(w, "estimate")
    assert '"narration_chars":' in result.content and not result.is_error
