"""The assistant's operations on a working copy of a spec: pure, with GAM faked."""

import json
import threading

import pytest

from app.assistant import clips, loop
from app.assistant import tools as T
from app.assistant.tools import Working
from app.gam.client import GamClient
from app.providers.base import ProviderError, ToolCall
from tests.fake_provider import ScriptedProvider, call, says
from tests.fake_siblings import gam_asset, hit, transcript


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


def river_transcript(siblings):
    # The transcriber's segments break mid-sentence, as they do wherever someone pauses.
    siblings.transcripts["r"] = transcript(
        "r",
        (30.0, 36.0, "We came here in the spring.", 0),
        (36.5, 42.0, "Back then the river ran", 0),
        (42.0, 47.5, "clear all year, but now the water is gone.", 0),
        (48.0, 52.0, "Nobody planned for that.", 1),
    )


def test_a_transcript_reads_as_whole_sentences_with_their_times(gam, siblings):
    river_transcript(siblings)
    w = Working(spec(), gam=gam)
    read = run(w, "read_transcript", gam_id="r")
    assert not read.is_error
    assert read.content.splitlines()[1:] == [
        "[30.0-36.0] S0: We came here in the spring.",
        "[36.5-47.5] Back then the river ran clear all year, but now the water is gone.",
        "[48.0-52.0] S1: Nobody planned for that.",
    ]


def test_a_transcript_can_be_read_a_stretch_at_a_time(gam, siblings, monkeypatch):
    river_transcript(siblings)
    w = Working(spec(), gam=gam)
    stretch = run(w, "read_transcript", gam_id="r", start=40, end=50).content
    assert "Back then" in stretch and "Nobody" in stretch and "spring" not in stretch

    monkeypatch.setattr(T, "MAX_TRANSCRIPT_CHARS", 60)
    page = run(w, "read_transcript", gam_id="r").content
    assert "spring" in page and "river" not in page
    assert "read_transcript with start 36.5" in page
    # Asked once, however often it is read.
    assert sum(r.url.path.endswith("/transcript") for r in siblings.gam_requests()) == 1


def test_an_untranscribed_video_says_so(gam, siblings):
    w = Working(spec(), gam=gam)
    assert "no transcript" in run(w, "read_transcript", gam_id="r").content
    assert run(w, "read_transcript", gam_id="nope").is_error


def test_a_segment_corrected_by_hand_is_read_as_its_text(gam, siblings):
    river_transcript(siblings)
    segment = siblings.transcripts["r"]["segments"][0]
    segment["text"], segment["edited"] = "We came here in late spring.", True
    w = Working(spec(), gam=gam)
    assert "[30.0-36.0] S0: We came here in late spring." in run(w, "read_transcript", gam_id="r").content


def test_a_found_moment_is_cut_as_the_whole_sentence_it_falls_in(gam, siblings):
    river_transcript(siblings)
    w = Working(spec(), gam=gam)
    run(w, "search_assets", query="water")
    run(w, "set_visual", segment_id="s_valley", gam_id="r")
    # The hit is 42-47.5, the back half of a sentence that starts at 36.5. The cut takes
    # the whole sentence, and its padding stops where the next one begins.
    assert w.data["segments"][1]["visual"]["trim"] == {"in": 36.0, "out": 48.0}


def test_a_hit_says_when_more_of_the_video_matched(gam, siblings):
    siblings.hits = [hit(siblings.assets["r"], start=42.0, end=47.5, other_matches=3)]
    w = Working(spec(), gam=gam)
    assert '"more_moments":3' in run(w, "search_assets", query="water").content


def test_a_track_hit_says_what_it_sounds_like(gam, siblings):
    siblings.hits = [
        hit(gam_asset("m1", "Caravan theme", "audio", music_genres=["Ambient"],
                      music_moods=["Tense"], music_instruments=[], music_bpm=91.6,
                      music_key=None, music_vocals=False, music_energy="low")),
        hit(gam_asset("m2", "Untagged song", "audio")),
    ]
    w = Working(spec(), gam=gam)
    found = run(w, "search_assets", query="tense ambient", type="audio").content

    # Only what is known: no empty instruments, no null key, and vocals as the word that
    # matters under narration.
    assert ('"music":{"genres":["Ambient"],"moods":["Tense"],"bpm":92,"energy":"low",'
            '"vocals":"instrumental"}') in found
    # A track with no profile carries no music key at all, rather than an empty one.
    untagged = found.split('"Untagged song"')[1]
    assert '"music"' not in untagged


def test_a_hit_says_whether_it_is_music_or_a_voice(gam, siblings):
    siblings.hits = [
        hit(gam_asset("m1", "Theme", "audio", audio_kind="music", music_genres=["Ambient"])),
        hit(gam_asset("v1", "Voice memo", "audio", audio_kind="speech")),
        hit(gam_asset("u1", "Unknown", "audio")),
    ]
    w = Working(spec(), gam=gam)
    found = run(w, "search_assets", query="calm", type="audio").content

    assert '"name":"Theme","type":"audio","kind":"music","music":{"genres":["Ambient"]}' in found
    assert '"name":"Voice memo","type":"audio","kind":"speech"' in found
    assert '"kind"' not in found.split('"Unknown"')[1]


def test_get_asset_includes_the_music_profile(gam, siblings):
    siblings.assets["m1"] = gam_asset("m1", "Caravan theme", "audio", music_vocals=True)
    w = Working(spec(), gam=gam)
    assert '"music":{"vocals":"yes"}' in run(w, "get_asset", gam_id="m1").content


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


def test_a_generated_picture_is_a_placeholder_started_at_once_up_to_the_cap():
    started = []

    def generate(data, key, prompt, base_ids, outputs):
        assert data["assets"][key] == {"from": "generate", "type": "image", "prompt": prompt}
        started.append((key, base_ids, outputs))
        return "FLUX.1 [schnell]", 0.003

    w = Working(spec(), max_generations=2)
    w.generate = generate
    result = run(w, "generate_image", prompt="The dam at dusk, wide", segment_id="s_valley")
    assert not result.is_error and "about $0.003" in result.content
    assert w.data["segments"][1]["visual"] == {"asset": started[0][0]}
    run(w, "generate_image", prompt="A gauge", segment_id="s_valley", use_as="overlay",
        outputs=9, base_gam_ids=["p"])
    assert w.data["segments"][1]["overlays"][0]["asset"] == started[1][0]
    assert started[1][1:] == (["p"], 4)
    capped = run(w, "generate_image", prompt="One more", use_as="none")
    assert capped.is_error and "add_placeholder" in capped.content and len(started) == 2
    assert w.valid


def test_a_generation_that_cannot_start_leaves_the_placeholder():
    def generate(*_):
        raise RuntimeError("no fal.ai key")

    w = Working(spec())
    w.generate = generate
    result = run(w, "generate_image", prompt="A dam", segment_id="s_valley")
    assert not result.is_error and "no fal.ai key" in result.content
    key = w.data["segments"][1]["visual"]["asset"]
    assert w.data["assets"][key]["from"] == "generate" and w.generated == 0


def test_a_notes_files_are_copied_into_the_library_once_and_registered(siblings):
    siblings.notes_files = {"/media/u1/map.png": b"map", "/media/u1/pan.mp4": b"pan"}
    w = Working(spec(), gam=GamClient("user-token"), note_media={
        "n1": {"type": "image", "path": "/media/u1/map.png", "name": "map.png",
               "caption": "Old map", "after": "The valley"},
        "n2": {"type": "video", "path": "/media/u1/pan.mp4", "name": "pan.mp4",
               "caption": "", "after": ""},
        "n3": {"type": "image", "path": "/media/u1/gone.png", "name": "gone.png",
               "caption": "", "after": ""},
    })

    result = run(w, "import_note_media", media_ids=["n1", "n2", "n3"])

    assert not result.is_error, result.content
    assert "Could not copy" in result.content and "n3" in result.content
    assets = {k: v for k, v in w.data["assets"].items() if k != "a_map"}
    assert sorted(a["id"] for a in assets.values()) == ["gam-1", "gam-2"]
    assert {a["type"] for a in assets.values()} == {"image", "video"}
    assert "a_old_map" in assets

    # The key it returned is usable at once, and asking again uploads nothing new.
    assert not run(w, "set_visual", segment_id="s_valley", asset="a_old_map").is_error
    run(w, "import_note_media", media_ids=["n1"])
    assert len(siblings.uploads) == 2


def test_only_the_ids_of_attached_notes_can_be_imported(siblings):
    w = Working(spec(), gam=GamClient("user-token"), note_media={})
    assert run(w, "import_note_media", media_ids=["n1"]).is_error
    w.note_media = {"n1": {"type": "image", "path": "/media/u1/a.png", "name": "a",
                           "caption": "", "after": ""}}
    result = run(w, "import_note_media", media_ids=["/etc/passwd"])
    assert result.is_error and "No such note file" in result.content


def picker(*answers):
    """A clip-picking pass, recording what it was asked. Answers from a list in order, or
    from a function of the prompt where calls run at once and their order isn't fixed."""
    asked = []
    lock = threading.Lock()

    def ask(system, prompt):
        with lock:
            asked.append(prompt)
            n = len(asked)
        return answers[0](prompt) if callable(answers[0]) else answers[n - 1]
    ask.asked = asked
    return ask


def test_find_clips_reads_the_whole_video_and_returns_ready_cuts(gam, siblings):
    river_transcript(siblings)
    w = Working(spec(), gam=gam)
    run(w, "search_assets", query="water")
    w.ask = picker('Here you go:\n```json\n[{"first": 1, "last": 2, "score": 9, '
                   '"why": "Says the river dried up and that nobody planned for it."},'
                   '{"first": 0, "last": 0, "score": 3, "why": "weak"}]\n```')
    found = run(w, "find_clips", gam_id="r", idea="The river ran dry without warning")
    assert not found.is_error, found.content
    result = json.loads(found.content)
    # Lines 1-2 run 36.5-52.0; padded into the gap before, the video's end after. The
    # weak passage is dropped.
    assert [c["trim"] for c in result["clips"]] == [{"in": 36.0, "out": 52.5}]
    assert result["clips"][0]["says"].startswith("Back then the river ran clear")
    # The picker saw every line, numbered, and the idea.
    prompt = w.ask.asked[0]
    assert "The idea: The river ran dry without warning" in prompt
    assert "0 [30.0-36.0] We came here" in prompt and "2 [48.0-52.0] Nobody" in prompt

    # Asked again, it isn't paid for again.
    assert run(w, "find_clips", gam_id="r", idea="the river ran dry without warning ").content \
        == found.content
    assert len(w.ask.asked) == 1 and w.picks == 1


def test_find_clips_never_cuts_what_the_picker_did_not_read(gam, siblings):
    river_transcript(siblings)
    w = Working(spec(), gam=gam)
    w.ask = picker('[{"first": 2, "last": 9, "score": 10}, {"first": "x"}, '
                   '{"first": 2, "last": 1, "score": 8}]')
    assert "Nothing in this video" in run(w, "find_clips", gam_id="r", idea="water").content


def test_find_clips_reads_a_long_video_in_windows_and_keeps_the_best(gam, siblings, monkeypatch):
    river_transcript(siblings)
    monkeypatch.setattr(clips, "MAX_PICK_CHARS", 90)
    monkeypatch.setattr(clips, "WINDOW_OVERLAP", 1)
    w = Working(spec(), gam=gam)
    spans = clips.windows(T.sentences(w.transcript("r")))
    assert spans[0][0] == 0 and spans[-1][1] == 3 and len(spans) > 1
    def answer(prompt):
        # Each window offers its own first line, scored by how late the window comes.
        i = next(n for n, (start, _) in enumerate(spans) if f"\n{start} [" in prompt)
        return '[{"first": %d, "last": %d, "score": %d}]' % (spans[i][0], spans[i][0], 5 + i)
    w.ask = picker(answer)
    result = json.loads(run(w, "find_clips", gam_id="r", idea="water", count=1).content)
    assert len(result["clips"]) == 1 and result["clips"][0]["score"] == 5 + len(spans) - 1
    assert w.picks == len(spans)
    assert "lines" in w.ask.asked[0] and "read separately" in w.ask.asked[0]


def test_find_clips_stops_at_its_budget_and_says_what_to_do_instead(gam, siblings):
    river_transcript(siblings)
    w = Working(spec(), gam=gam, max_picks=0)
    w.ask = picker()
    refused = run(w, "find_clips", gam_id="r", idea="water")
    assert refused.is_error and "read_transcript" in refused.content


def test_find_clips_without_a_picker_or_a_transcript_says_so(gam, siblings):
    w = Working(spec(), gam=gam)
    assert run(w, "find_clips", gam_id="r", idea="water").is_error
    w.ask = picker()
    assert "no transcript" in run(w, "find_clips", gam_id="r", idea="water").content
    assert run(w, "find_clips", gam_id="r", idea="water", count="a few").is_error


def test_overlapping_passages_are_kept_once_in_the_order_said():
    found = [clips.Clip(4, 6, 7, ""), clips.Clip(5, 8, 9, ""), clips.Clip(0, 1, 6, ""),
             clips.Clip(10, 10, 8, "")]
    assert [(c.first, c.last) for c in clips.best(found, 3)] == [(0, 1), (5, 8), (10, 10)]


def two_videos(siblings):
    river_transcript(siblings)
    siblings.assets["d"] = gam_asset("d", "Dam engineer", "video", duration_seconds=300.0)
    siblings.transcripts["d"] = transcript(
        "d", (10.0, 16.0, "We built the dam in nineteen eighty."),
        (16.5, 24.0, "Nobody downstream was asked."))


def clip_call(gam_id, idea="water"):
    return ToolCall(id=f"pick-{gam_id}", name="find_clips",
                    arguments={"gam_id": gam_id, "idea": idea})


def test_the_picker_calls_of_one_round_run_at_once(gam, siblings):
    two_videos(siblings)
    w = Working(spec(), gam=gam)
    # Each call waits for the other: made one after another, the first would wait
    # forever (here, until the barrier gives up and the test fails).
    both = threading.Barrier(2, timeout=5)

    def ask(system, prompt):
        both.wait()
        return '[{"first": 1, "last": 1, "score": 8}]'
    w.ask = ask
    jobs = [T.plan(w, clip_call("r")), T.plan(w, clip_call("d"))]
    assert all(isinstance(job, T.ClipJob) for job in jobs) and w.picks == 2
    answers = T.finish_clip_jobs(w, jobs)
    assert [json.loads(content)["gam_id"] for content, _ in answers] == ["r", "d"]
    assert "Back then" in answers[0][0] and "Nobody downstream" in answers[1][0]


def test_no_more_picker_calls_run_at_once_than_allowed(gam, siblings, monkeypatch):
    two_videos(siblings)
    monkeypatch.setattr(clips, "MAX_PICK_CHARS", 60)
    w = Working(spec(), gam=gam, pick_concurrency=2)
    running, most, lock = [0], [0], threading.Lock()

    def ask(system, prompt):
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        threading.Event().wait(0.05)
        with lock:
            running[0] -= 1
        return "[]"
    w.ask = ask
    jobs = [T.plan(w, clip_call("r")), T.plan(w, clip_call("d"))]
    assert sum(len(job.prompts) for job in jobs) > 2
    T.finish_clip_jobs(w, jobs)
    assert most[0] == 2


def test_one_videos_failed_pick_leaves_the_others_standing(gam, siblings):
    two_videos(siblings)
    w = Working(spec(), gam=gam)

    def ask(system, prompt):
        if "Dam engineer" in prompt:
            raise ProviderError("Claude: overloaded")
        return '[{"first": 1, "last": 1, "score": 8}]'
    w.ask = ask
    run(w, "search_assets", query="water")
    siblings.hits = [hit(siblings.assets["d"], start=10.0, end=16.0)]
    run(w, "search_assets", query="dam")
    river, dam = T.finish_clip_jobs(w, [T.plan(w, clip_call("r")), T.plan(w, clip_call("d"))])
    assert not river[1] and "Back then" in river[0]
    assert dam[1] and "overloaded" in dam[0] and "read_transcript" in dam[0]
    # Only the answer that came back is kept for asking again.
    assert ("d", "water", 3) not in w.picked and ("r", "water", 3) in w.picked


def test_a_round_answers_its_calls_in_order_with_the_picks_made_together(gam, siblings):
    two_videos(siblings)
    w = Working(spec(), gam=gam)
    w.ask = picker(lambda prompt: '[{"first": 0, "last": 0, "score": 7}]')
    provider = ScriptedProvider(script=[
        says("", clip_call("r"), call("get_spec", segment_id="s_title"), clip_call("d"),
             call("find_clips", gam_id="r", idea="")),
        says("Found them."),
    ])
    steps = []
    loop.run(provider, w, system=[], history=[], prompt="clips", on_step=lambda k, t:
             steps.append(t), on_reply=lambda r: None, cancelled=lambda: False, max_rounds=3)
    results = provider.results()
    assert [r.call_id for r in results] == ["pick-r", results[1].call_id, "pick-d",
                                            results[3].call_id]
    assert "We came here" in results[0].content and "s_title" in results[1].content
    assert "We built the dam" in results[2].content and results[3].is_error
    assert len(w.ask.asked) == 2
    assert "Picking clips from d" in steps
