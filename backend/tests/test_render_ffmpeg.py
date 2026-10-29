"""Copied from gecko-notes' tests/test_video_ffmpeg.py with the engine it covers.

Tests of Notes' shot timeline and estimate are left behind: GVC lays out its own
timeline (app/render/compile.py) and tests it there.
"""

import json
import math
import os
import tempfile
import types

import pytest

from app.render import ffmpeg as F
from app.render.narration import (
    Cue, _srt_timestamp, build_narration_chunks, chunk_narration, chunk_text,
    shift_cues, split_for_subtitles, strip_emoji, write_srt,
)
from app.render.options import (
    KENBURNS_MIN_LEG_SECONDS, KENBURNS_PREVIEW_READ_PIXELS, MusicSpec, RenderOptions,
    encoder_tier, frame_size,
    kenburns_geometry,
)


@pytest.fixture(autouse=True)
def _all_filters_present(monkeypatch):
    """Pretend the host ffmpeg has everything, so tests exercise the full graph."""
    monkeypatch.setattr(F, "_filter_cache", frozenset({
        "showwaves", "gblur", "subtitles", "drawbox", "overlay", "asplit", "apad",
        "zoompan", "xfade", "concat", "sidechaincompress", "fade", "afade",
    }))


def _graph(argv):
    return argv[argv.index("-filter_complex") + 1]


# ── frame sizes and encoder tiers ────────────────────────────────────────────

@pytest.mark.parametrize("aspect,resolution,expected", [
    ("16:9", "720p", (1280, 720)),
    ("16:9", "1080p", (1920, 1080)),
    ("16:9", "4k", (3840, 2160)),
    ("9:16", "1080p", (1080, 1920)),
    ("1:1", "720p", (720, 720)),
])
def test_frame_size_table(aspect, resolution, expected):
    assert frame_size(aspect, resolution) == expected


def test_every_frame_size_is_even_as_yuv420p_requires():
    for aspect in ("16:9", "9:16", "1:1"):
        for resolution in ("720p", "1080p", "4k"):
            for preview in (False, True):
                w, h = frame_size(aspect, resolution, preview)
                assert w % 2 == 0 and h % 2 == 0


def test_unknown_aspect_and_resolution_fall_back():
    assert frame_size("banana", "1080p") == (1920, 1080)
    assert frame_size("16:9", "banana") == (1920, 1080)


def test_preview_overrides_the_chosen_quality():
    assert frame_size("16:9", "4k", preview=True) == (854, 480)
    assert encoder_tier("high", preview=True) == ("ultrafast", 30)
    assert encoder_tier("high") == ("slow", 18)


# ── uniform encoding, which is what makes `concat -c copy` valid ─────────────

def test_every_shot_kind_encodes_identically():
    options = RenderOptions()
    graphs = [
        F.build_shot_command(kind="still", background="a.png", audio="n.wav", duration=3,
                             output="0.mp4", options=options, preview=False),
        F.build_shot_command(kind="video_muted", background="c.mp4", audio="n.wav", duration=3,
                             output="1.mp4", options=options, preview=False),
        F.build_shot_command(kind="video_sound", background="c.mp4", audio=None, duration=3,
                             output="2.mp4", options=options, preview=False,
                             background_has_audio=True),
    ]
    encode = F.encode_args(options, False)
    for argv in graphs:
        assert argv[-len(encode) - 1:-1] == encode


def test_concat_copies_rather_than_re_encoding():
    argv = F.build_concat_command("shots.txt", "out.mp4")
    assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"
    assert "+faststart" in argv
    assert "libx264" not in argv


# ── per-shot commands ────────────────────────────────────────────────────────

def test_muted_video_loops_and_is_cut_by_the_narration():
    argv = F.build_shot_command(kind="video_muted", background="c.mp4", audio="n.wav",
                                duration=7.25, output="s.mp4", options=RenderOptions(),
                                preview=False)
    # Loop while the narration runs...
    assert argv[argv.index("-stream_loop") + 1] == "-1"
    # ...and cut the instant it ends, never waiting for the clip.
    assert argv[argv.index("-t") + 1] == "7.250"


def test_still_shot_holds_one_frame_for_the_narration():
    argv = F.build_shot_command(kind="still", background="bg.png", audio="n.wav", duration=4,
                                output="s.mp4", options=RenderOptions(), preview=False)
    assert "-loop" in argv and argv[argv.index("-loop") + 1] == "1"


def test_sounded_clip_uses_its_own_audio():
    argv = F.build_shot_command(kind="video_sound", background="c.mp4", audio=None, duration=2,
                                output="s.mp4", options=RenderOptions(), preview=False,
                                background_has_audio=True)
    assert "anullsrc" not in " ".join(argv)
    assert "[0:a]" in _graph(argv)


def test_a_sounded_clip_holds_its_last_frame_rather_than_running_short():
    """A blend's tail can ask for more than the file has after the out point."""
    argv = F.build_shot_command(kind="video_sound", background="c.mp4", audio=None, duration=2,
                                output="s.mp4", options=RenderOptions(), preview=False,
                                background_has_audio=True, loop=False)
    assert "tpad=stop_mode=clone" in _graph(argv)
    assert "-stream_loop" not in argv


def test_sounded_clip_without_an_audio_track_gets_silence():
    """The concat demuxer needs every part to carry an audio stream."""
    argv = F.build_shot_command(kind="video_sound", background="c.mp4", audio=None, duration=2,
                                output="s.mp4", options=RenderOptions(), preview=False,
                                background_has_audio=False)
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in argv
    assert "[1:a]" in _graph(argv)


# ── filtergraph shape ────────────────────────────────────────────────────────

@pytest.mark.parametrize("fit,marker", [
    ("blur", "gblur"),
    ("pad", "pad=1920:1080"),
    ("crop", "crop=1920:1080"),
])
def test_fit_modes(fit, marker):
    argv = F.build_shot_command(kind="still", background="bg.png", audio="n.wav", duration=3,
                                output="s.mp4", options=RenderOptions(fit=fit), preview=False)
    assert marker in _graph(argv)


def test_blurred_fill_contains_the_image_over_a_filled_background():
    graph = F.fit_chain("0:v", "fit", 1080, 1920, "blur")
    assert "force_original_aspect_ratio=increase" in graph   # the blurred fill
    assert "force_original_aspect_ratio=decrease" in graph   # the contained image
    assert "gblur" in graph


def test_every_video_chain_ends_normalised():
    """A stray SAR or pixel format is what silently breaks a `-c copy` concat."""
    for kind, audio, has_audio in (
        ("still", "n.wav", False), ("video_muted", "n.wav", False), ("video_sound", None, True),
    ):
        graph = _graph(F.build_shot_command(
            kind=kind, background="x", audio=audio, duration=3, output="o.mp4",
            options=RenderOptions(), preview=False, background_has_audio=has_audio))
        assert f"{F.NORMALISE}[v]" in graph


def test_waveform_splits_the_audio_it_shares_with_the_muxed_track():
    """An input pad can only be consumed once in a filtergraph."""
    options = RenderOptions()
    options.waveform.enabled = True
    graph = _graph(F.build_shot_command(kind="still", background="bg.png", audio="n.wav",
                                        duration=3, output="s.mp4", options=options, preview=False))
    assert "[1:a]asplit=2[a_wave][a_main]" in graph
    assert graph.count("[1:a]") == 1


def test_waveform_rate_matches_the_output_frame_rate():
    """A mismatch makes the wave drift against the picture."""
    options = RenderOptions(fps=24)
    options.waveform.enabled = True
    graph = _graph(F.build_shot_command(kind="still", background="bg.png", audio="n.wav",
                                        duration=3, output="s.mp4", options=options, preview=False))
    assert "rate=24" in graph


@pytest.mark.parametrize("position,expected_y", [
    ("top", 0), ("center", (1080 - 236) // 2), ("bottom", 1080 - 236),
])
def test_waveform_position(position, expected_y):
    options = RenderOptions()
    options.waveform.enabled = True
    options.waveform.position = position
    graph = _graph(F.build_shot_command(kind="still", background="bg.png", audio="n.wav",
                                        duration=3, output="s.mp4", options=options, preview=False))
    assert f"overlay=0:{expected_y}" in graph


def test_waveform_is_dropped_when_the_host_ffmpeg_lacks_it(monkeypatch):
    monkeypatch.setattr(F, "_filter_cache", frozenset({"overlay"}))
    options = RenderOptions()
    options.waveform.enabled = True
    graph = _graph(F.build_shot_command(kind="still", background="bg.png", audio="n.wav",
                                        duration=3, output="s.mp4", options=options, preview=False))
    assert "showwaves" not in graph
    assert f"{F.NORMALISE}[v]" in graph  # still a valid graph


def test_overlay_and_subtitles_are_layered_in_order():
    graph = _graph(F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=3, output="s.mp4",
        options=RenderOptions(), preview=False, overlay_png="ov.png", subtitle_file="s.srt"))
    assert graph.index("[2:v]overlay=0:0[ov]") < graph.index("subtitles=s.srt")


def test_colour_parsing_is_forgiving():
    assert F._hex_to_ffmpeg("#00FF41") == "0x00ff41"
    assert F._hex_to_ffmpeg("00ff41") == "0x00ff41"
    assert F._hex_to_ffmpeg("#abc") == "0xaabbcc"
    assert F._hex_to_ffmpeg("#00ff41ff") == "0x00ff41"
    assert F._hex_to_ffmpeg("nonsense") == "0xffffff"
    assert F._hex_to_ffmpeg("") == "0xffffff"


# ── muxing ───────────────────────────────────────────────────────────────────

def test_mux_attaches_chapters_and_soft_subtitles_without_re_encoding():
    argv = F.build_mux_command("in.mp4", "out.mp4", chapters_file="c.ff", subtitle_file="s.srt")
    assert argv[argv.index("-c") + 1] == "copy"
    assert argv[argv.index("-c:s") + 1] == "mov_text"
    assert "-map_chapters" in argv


def test_mux_with_nothing_to_attach_still_copies():
    argv = F.build_mux_command("in.mp4", "out.mp4")
    assert "-c:s" not in argv and "-map_chapters" not in argv


# ── narration joining ────────────────────────────────────────────────────────

def test_narration_decodes_to_pcm_so_the_join_has_no_gaps():
    argv = F.build_narration_command("list.txt", "n.wav")
    assert argv[argv.index("-c:a") + 1] == "pcm_s16le"


def test_speed_beyond_atempos_range_is_applied_in_stages():
    """atempo only accepts 0.5-2.0."""
    single = F.build_narration_command("l.txt", "n.wav", speed=1.5)
    assert "atempo=1.5000" in single[single.index("-filter:a") + 1]

    chained = F.build_narration_command("l.txt", "n.wav", speed=3.0)
    assert chained[chained.index("-filter:a") + 1].count("atempo") == 2

    assert "-filter:a" not in F.build_narration_command("l.txt", "n.wav", speed=1.0)


def test_narration_is_padded_to_the_minimum_shot_length():
    argv = F.build_narration_command("l.txt", "n.wav", min_seconds=2.5)
    assert "apad=whole_dur=2.500" in argv[argv.index("-filter:a") + 1]


def test_concat_list_quotes_each_entry():
    import tempfile
    path = tempfile.mktemp()
    F.write_concat_list(path, ["shot_000.mp4", "it's.mp4"])
    body = open(path).read()
    assert body.splitlines()[0] == "file 'shot_000.mp4'"
    assert "'\\''" in body.splitlines()[1]


@pytest.mark.parametrize("code,stderr,expected", [
    (-9, b"", "killed by signal 9 (most likely out of memory)"),
    (1, b"Invalid argument", "exit code 1): Invalid argument"),
])
def test_run_failure_reports_how_the_process_died(monkeypatch, code, stderr, expected):
    result = types.SimpleNamespace(returncode=code, stderr=stderr)
    monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: result)
    with pytest.raises(F.FFmpegError) as err:
        F.run(["ffmpeg", "-i", "x"])
    assert expected in str(err.value)


# ── chunking ─────────────────────────────────────────────────────────────────

def test_short_text_is_one_chunk():
    assert chunk_text("Hello there. How are you?") == ["Hello there. How are you?"]


def test_empty_text_produces_nothing():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunks_stay_under_the_providers_character_cap():
    text = " ".join(f"Sentence number {i} is right here." for i in range(400))
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 1500 for c in chunks)
    # Nothing is dropped on the way through.
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_a_sentence_is_kept_whole_when_the_chunk_is_full():
    """A sentence that fits the cap starts a new chunk rather than being cut."""
    long_sentence = ("A " * 745).strip() + "."      # 1490 chars — fits on its own
    text = f"{long_sentence} Short one."             # together they exceed 1500
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0] == long_sentence
    assert chunks[1] == "Short one."


def test_an_over_long_sentence_is_split_on_a_word_boundary():
    chunks = chunk_text("word " * 800)
    assert len(chunks) > 1
    assert all(not c.startswith(" ") and "  " not in c for c in chunks)
    assert all(len(c) <= 1500 for c in chunks)


def test_an_unbroken_run_is_split_by_length_as_a_last_resort():
    chunks = chunk_text("x" * 4000)
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 4000


def test_strip_emoji_drops_pictographs_but_keeps_plain_text():
    assert strip_emoji("I drove my car \U0001F697 to work.") == "I drove my car  to work."
    assert strip_emoji("No emoji here, just #hashtag and 100% normal text.") == \
        "No emoji here, just #hashtag and 100% normal text."
    assert strip_emoji(":) plain smiley text stays") == ":) plain smiley text stays"


def test_strip_emoji_drops_modifiers_and_compound_sequences():
    # Skin-tone modifier, ZWJ family sequence, flag pair, keycap sequence.
    assert strip_emoji("Great \U0001F44D\U0001F3FD job") == "Great  job"
    assert strip_emoji("Family \U0001F468‍\U0001F469‍\U0001F467 photo") == "Family  photo"
    assert strip_emoji("Flags \U0001F1FA\U0001F1F8 here") == "Flags  here"
    assert strip_emoji("Step 1️⃣ done") == "Step 1 done"


def test_chunk_text_strips_emoji_so_narration_never_speaks_them():
    chunks = chunk_text("Great job! \U0001F44D Keep it up.")
    assert chunks == ["Great job! Keep it up."]


# ── subtitles ────────────────────────────────────────────────────────────────

def test_subtitle_lines_stay_readable():
    """A whole TTS chunk is far too much text to show at once."""
    text = " ".join(f"This is sentence {i} of the narration." for i in range(30))
    lines = split_for_subtitles(text)
    assert lines
    assert all(len(l) <= 84 for l in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_a_single_long_word_is_still_broken_up():
    lines = split_for_subtitles("supercalifragilistic " * 20)
    assert all(len(l) <= 84 for l in lines)


def test_srt_timestamps():
    assert _srt_timestamp(0) == "00:00:00,000"
    assert _srt_timestamp(3661.5) == "01:01:01,500"
    assert _srt_timestamp(-5) == "00:00:00,000"


def test_write_srt_numbers_cues_and_skips_empty_ones():
    import tempfile
    path = tempfile.mktemp()
    assert write_srt(path, [Cue(0, 1, "first"), Cue(1, 2, "   "), Cue(2, 3, "second")])
    body = open(path).read()
    assert body.startswith("1\n00:00:00,000 --> 00:00:01,000\nfirst\n")
    assert "2\n00:00:02,000 --> 00:00:03,000\nsecond\n" in body
    assert body.count("-->") == 2


def test_write_srt_reports_when_there_was_nothing_to_write():
    import tempfile
    assert write_srt(tempfile.mktemp(), []) is False
    assert write_srt(tempfile.mktemp(), [Cue(1.0, 1.0, "zero length")]) is False


# ── options validation ───────────────────────────────────────────────────────

def test_out_of_range_options_are_clamped_rather_than_rejected():
    assert RenderOptions(fps=999).fps == 60
    assert RenderOptions(fps=1).fps == 12
    assert RenderOptions(speed=9).speed == 2.0
    assert RenderOptions(speed=0.01).speed == 0.5
    assert RenderOptions(paragraph_pause_ms=-5).paragraph_pause_ms == 0
    assert RenderOptions(min_shot_seconds=999).min_shot_seconds == 30.0
    assert RenderOptions(shot_end_pause_ms=-5).shot_end_pause_ms == 0
    assert RenderOptions(shot_end_pause_ms=99999).shot_end_pause_ms == 3000


def test_shot_end_pause_defaults_on():
    """Confirmed as a real bug and the reason this option exists: without a
    trailing pause, a shot's audio stops the instant speech does, often
    mid-decay on the voice's own trailing intonation, and the cut lands right
    on top of it — it reads as the sentence getting clipped, not finishing."""
    assert RenderOptions().shot_end_pause_ms > 0


# ── transitions ──────────────────────────────────────────────────────────────

def _shot(options, *, kind="still", duration=6.0, index=0):
    return F.build_shot_command(
        kind=kind, background="bg.png", audio="n.wav", duration=duration,
        output="s.mp4", options=options, preview=False, index=index,
    )


@pytest.mark.parametrize("style,colour", [("fade", "black"), ("fadewhite", "white")])
def test_a_dip_transition_fades_the_picture_and_only_the_sounds_tail(style, colour):
    graph = _graph(_shot(RenderOptions(transition={"style": style, "duration": 0.6})))
    assert f"fade=t=in:st=0:d=0.600:color={colour}" in graph
    assert f"fade=t=out:st=5.400:d=0.600:color={colour}" in graph
    # The tail is faded to match the picture dipping to colour there, landing in
    # the trailing hold after the last word rather than on speech.
    assert "afade=t=out:st=5.400:d=0.600" in graph
    # But not the head: narration starts at st=0 with no lead-in silence, so a
    # matching fade-in there would ramp up through the sentence's actual first
    # word instead of the picture's cosmetic fade from black.
    assert "afade=t=in" not in graph


def test_a_dip_never_takes_more_than_a_third_of_a_short_shot():
    """Two 0.6s dips on a 1.2s shot would never let the picture be fully seen."""
    assert F.dip_seconds("fade", 0.6, 1.2) == pytest.approx(0.4)
    assert F.dip_seconds("fade", 0.6, 30.0) == pytest.approx(0.6)


def test_a_dip_too_short_to_see_is_dropped_entirely():
    assert F.dip_seconds("fade", 0.6, 0.09) == 0.0
    graph = _graph(_shot(RenderOptions(transition={"style": "fade"}), duration=0.09))
    assert "fade=t=in" not in graph


def test_a_crossfade_style_draws_no_per_shot_fade():
    """A blend happens between shots, so drawing one inside a shot as well would
    dip to black and then dissolve out of it."""
    graph = _graph(_shot(RenderOptions(transition={"style": "dissolve"})))
    assert "fade=t=in" not in graph and "afade=" not in graph


def test_no_transition_leaves_the_graph_as_it_was():
    graph = _graph(_shot(RenderOptions()))
    assert "fade=" not in graph
    assert graph.endswith("aresample=48000,aformat=channel_layouts=stereo,apad[a]")


def test_a_dip_is_left_off_the_end_that_joins_by_a_straight_cut():
    """Where a heading carries a section on over the same picture, dipping to
    black and back would show nothing changing."""
    options = RenderOptions(transition={"style": "fade", "duration": 0.6})
    into = _graph(F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=6.0, output="s.mp4",
        options=options, preview=False, dip_in=False))
    assert "fade=t=in" not in into
    assert "fade=t=out:st=5.400:d=0.600:color=black" in into
    assert "afade=t=out:st=5.400:d=0.600" in into

    out_of = _graph(F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=6.0, output="s.mp4",
        options=options, preview=False, dip_out=False))
    assert "fade=t=in:st=0:d=0.600:color=black[fd]" in out_of
    assert "fade=t=out" not in out_of and "afade" not in out_of


# ── the crossfade stitch ─────────────────────────────────────────────────────

ALL = frozenset({"xfade", "concat"})


def test_crossfade_offsets_accumulate_across_the_whole_video():
    """Each join eats `overlap` seconds, so shot k starts that much earlier than
    the running total — get this wrong and every chapter after the first drifts."""
    argv = F.build_xfade_command(
        ["a.mp4", "b.mp4", "c.mp4"], [5.0, 4.0, 6.0], "out.mp4",
        options=RenderOptions(), preview=False, style="dissolve", overlap=0.6,
    )
    graph = _graph(argv)
    assert "[0:v][1:v]xfade=transition=dissolve:duration=0.600:offset=4.400[vx1]" in graph
    assert "[vx1][2:v]xfade=transition=dissolve:duration=0.600:offset=7.800[vx2]" in graph
    # The audio cuts cleanly at the same offset the picture starts blending at,
    # rather than crossfading — an acrossfade would mix the outgoing shot's
    # trailing hold with the next shot's opening words fading in underneath it.
    assert "acrossfade" not in graph
    assert "[0:a]atrim=end=4.400,asetpts=PTS-STARTPTS[at1]" in graph
    assert "[at1][1:a]concat=n=2:v=0:a=1[ax1]" in graph
    assert "[ax1]atrim=end=7.800,asetpts=PTS-STARTPTS[at2]" in graph
    assert "[at2][2:a]concat=n=2:v=0:a=1[ax2]" in graph
    assert argv[argv.index("-map") + 1] == "[v]"
    assert argv[argv.index("-movflags") + 1] == "+faststart" and argv[-1] == "out.mp4"


def test_every_shot_is_its_own_input_to_the_crossfade():
    argv = F.build_xfade_command(
        ["a.mp4", "b.mp4", "c.mp4"], [5.0, 4.0, 6.0], "out.mp4",
        options=RenderOptions(), preview=False, style="wipeleft", overlap=0.5,
    )
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "-i"] == ["a.mp4", "b.mp4", "c.mp4"]
    assert "transition=wipeleft" in _graph(argv)


def test_a_crossfade_shortens_the_video_by_one_overlap_per_join():
    assert F.crossfade_total([5.0, 4.0, 6.0], 0.6) == pytest.approx(13.8)
    assert F.crossfade_total([5.0, 4.0, 6.0], 0.0) == pytest.approx(15.0)
    assert F.crossfade_total([], 0.6) == 0.0


def test_a_shot_that_cuts_in_is_appended_whole_with_no_blend():
    argv = F.build_xfade_command(
        ["a.mp4", "b.mp4", "c.mp4"], [5.0, 4.0, 6.0], "out.mp4",
        options=RenderOptions(), preview=False, style="dissolve", overlap=0.6,
        cuts=[False, True, False],
    )
    graph = _graph(argv)
    assert "[0:v][1:v]concat=n=2:v=1:a=0[vx1]" in graph
    assert "[0:a][1:a]concat=n=2:v=0:a=1[ax1]" in graph
    # Nothing was eaten at the cut, so the blend into c starts at 9 - 0.6.
    assert "[vx1][2:v]xfade=transition=dissolve:duration=0.600:offset=8.400[vx2]" in graph
    assert "[ax1]atrim=end=8.400,asetpts=PTS-STARTPTS[at2]" in graph
    assert F.crossfade_total([5.0, 4.0, 6.0], 0.6, [False, True, False]) == pytest.approx(14.4)


def test_an_overlap_can_never_exceed_half_the_shortest_shot():
    """Overlapping more than a short shot's own length would blend it away."""
    assert F.crossfade_overlap("dissolve", [10.0, 1.0, 8.0], 0.6, filters=ALL) == pytest.approx(0.5)
    assert F.crossfade_overlap("dissolve", [10.0, 8.0], 0.6, filters=ALL) == pytest.approx(0.6)


def test_shots_too_short_to_overlap_fall_back_to_a_plain_concat():
    assert F.crossfade_overlap("dissolve", [0.08, 5.0], 0.6, filters=ALL) is None


def test_a_dip_or_no_transition_never_takes_the_crossfade_path():
    assert F.crossfade_overlap("fade", [5.0, 5.0], 0.6, filters=ALL) is None
    assert F.crossfade_overlap("none", [5.0, 5.0], 0.6, filters=ALL) is None


def test_a_single_shot_has_nothing_to_crossfade_into():
    assert F.crossfade_overlap("dissolve", [5.0], 0.6, filters=ALL) is None


def test_too_many_shots_fall_back_rather_than_build_a_vast_filtergraph():
    many = [5.0] * (F.XFADE_MAX_SHOTS + 1)
    assert F.crossfade_overlap("dissolve", many, 0.6, filters=ALL) is None
    assert F.crossfade_overlap("dissolve", [5.0] * F.XFADE_MAX_SHOTS, 0.6, filters=ALL) is not None


def test_a_host_without_xfade_falls_back_instead_of_failing_the_render():
    assert F.crossfade_overlap("dissolve", [5.0, 5.0], 0.6, filters=frozenset({"overlay"})) is None
    assert F.crossfade_overlap("dissolve", [5.0, 5.0], 0.6, filters=frozenset({"xfade"})) is None


# ── Ken Burns ────────────────────────────────────────────────────────────────

def _kb(effect="zoom_in", **kwargs):
    return RenderOptions(ken_burns={"effect": effect, **kwargs})


def test_a_drifting_still_reads_far_above_the_frame_and_writes_above_it_too():
    """zoompan truncates its crop origin to whole pixels of the frame it is
    handed, so a slow drift steps unless it is given many more of them. Reading
    big is most of the fix; writing big and scaling back down is the rest."""
    read_w, read_h, write_w, write_h = kenburns_geometry(1920, 1080)
    assert read_w >= 1920 * 3                  # a real supersample, not a token one
    assert (write_w, write_h) == (3840, 2160)  # written at 2x, then scaled back

    graph = _graph(_shot(_kb()))
    assert f"scale={read_w}:{read_h}" in graph
    assert f"s={write_w}x{write_h}" in graph
    assert "scale=1920:1080" in graph


FRAME_SIZES_TO_CHECK = ((854, 480), (1280, 720), (1920, 1080), (3840, 2160),
                        (1080, 1920), (2160, 3840))

EVERY_EFFECT = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down")


def _zoompan_rects(width, height, *, seconds, effect, amount=0.12, fps=30):
    """Replay a drift the way vf_zoompan does, one crop rectangle per frame.

    zoompan evaluates z, x and y once per output frame and then works entirely
    in whole pixels of the frame it was handed: `w = int(iw/zoom)`, likewise for
    h, and the origin truncated and clamped into whatever is left. Two frames
    with the same rectangle are two identical pictures, which is the whole
    subject of the tests below — so the arithmetic is reproduced here rather
    than taken on trust.
    """
    chain = F.kenburns_chain("in", "out", width=width, height=height, fps=fps,
                             duration=seconds, effect=effect, amount=amount)
    body = chain[chain.index("zoompan=") + len("zoompan="):].split(",")[0]
    exprs = {name: compile(value, "<zoompan>", "eval")
             for name, value in (part.split("=", 1) for part in body.split(":"))
             if name in ("z", "x", "y")}
    read_w, read_h, _w, _h = kenburns_geometry(width, height)
    scope = {"__builtins__": {}, "floor": math.floor, "abs": abs,
             "iw": read_w, "ih": read_h}

    rects = []
    for on in range(int(math.ceil(seconds * fps))):
        at = {**scope, "on": on}
        at["zoom"] = min(10.0, max(1.0, eval(exprs["z"], at)))
        w, h = int(read_w / at["zoom"]), int(read_h / at["zoom"])
        rects.append((
            w, h,
            min(max(0, int(eval(exprs["x"], at))), read_w - w),
            min(max(0, int(eval(exprs["y"], at))), read_h - h),
        ))
    return rects


@pytest.mark.parametrize("effect", EVERY_EFFECT)
@pytest.mark.parametrize("seconds", (2.5, 4.0, 15.0, 24.0, 60.0, 502.678))
def test_no_drift_ever_repeats_a_frame(effect, seconds):
    """The failure this whole arrangement exists to prevent, stated exactly.

    zoompan truncates the crop to whole pixels, so a drift that moves less than
    one of them in a frame lands on the rectangle it already had — and a pan,
    whose crop never changes size, then emits a byte-identical picture. The
    drift stops dead, then jumps.

    At 1080p and the default 12% this used to freeze one frame in eight of a
    15-second section and every other frame of a 30-second one. Worse, which
    frames froze was decided by the fractional part of the rate, so they
    clustered and thinned on a slow beat against the frame rate — around two
    seconds for a section of 16 to 24 seconds, which is what the drift
    "pausing every so often" actually was.
    """
    rects = _zoompan_rects(1920, 1080, seconds=seconds, effect=effect)
    frozen = [i for i in range(1, len(rects)) if rects[i] == rects[i - 1]]
    assert not frozen, f"{len(frozen)} frozen frames, first at frame {frozen[0]}"


@pytest.mark.parametrize("effect", EVERY_EFFECT)
@pytest.mark.parametrize("size", FRAME_SIZES_TO_CHECK)
def test_no_frame_size_repeats_a_frame_either(effect, size):
    """Every aspect and resolution reads at the same pixel budget, so none of
    them has more headroom to spend than any other."""
    rects = _zoompan_rects(*size, seconds=20.0, effect=effect)
    assert all(rects[i] != rects[i - 1] for i in range(1, len(rects)))


def test_a_drift_slow_enough_to_cycle_moves_exactly_one_pixel_a_frame():
    """Never repeating is half of it; the other half is moving by the *same*
    amount each time. A fractional rate rounds to one pixel on some frames and
    two on others, and the pattern of which is which beats slowly against the
    frame rate — so even without a single frozen frame the drift would visibly
    surge and ease. A pixel a frame is the one rate with no fractional part to
    beat, which is why the sweep rubber-bands at it rather than going slower."""
    rects = _zoompan_rects(1920, 1080, seconds=24.0, effect="pan_up")
    steps = {abs(rects[i][3] - rects[i - 1][3]) for i in range(1, len(rects))}
    assert steps == {1}


def test_a_shot_short_enough_to_sweep_once_is_allowed_to_move_faster():
    """Above a pixel a frame the rounding can only ever be one pixel or two,
    never none, so the full sweep is spent rather than rationed."""
    rects = _zoompan_rects(1920, 1080, seconds=4.0, effect="pan_up")
    steps = {abs(rects[i][3] - rects[i - 1][3]) for i in range(1, len(rects))}
    assert min(steps) >= 1 and max(steps) <= 4


@pytest.mark.parametrize("effect", EVERY_EFFECT)
def test_a_drift_still_spends_the_travel_it_was_asked_for(effect):
    """Never stalling would be easy if the drift simply moved less, so this
    pins the other end: each effect still crosses essentially all of the
    headroom the chosen zoom leaves it."""
    read_w, read_h, _w, _h = kenburns_geometry(1920, 1080)
    rects = _zoompan_rects(1920, 1080, seconds=15.0, effect=effect)
    if effect in ("pan_up", "pan_down"):
        room, axis = read_h - int(read_h / 1.12), 3
    elif effect.startswith("pan"):
        room, axis = read_w - int(read_w / 1.12), 2
    else:
        room, axis = read_w - int(read_w / 1.12), 0
    spent = max(r[axis] for r in rects) - min(r[axis] for r in rects)
    assert spent >= room * 0.98, f"{spent} of {room}"


def test_a_long_slow_drift_is_carried_by_the_downscale_not_by_reading_bigger():
    """A 12% zoom over 30s is a genuinely sub-pixel motion — the same travel over
    five times the frames — and no affordable read size fixes it. Writing above
    the frame and scaling back down is what keeps it smooth, because the step
    that survives lands at half size and gets averaged across the downscale."""
    for width, height in FRAME_SIZES_TO_CHECK:
        _r, _rh, write_w, write_h = kenburns_geometry(width, height)
        if (write_w, write_h) == (width, height):
            continue                             # 4K writes at frame size
        assert write_w >= width * 2 or write_h >= height * 2, (width, height)


def test_reading_is_never_smaller_than_writing():
    """That would have zoompan upscaling just to fill its own output."""
    for size in ((854, 480), (1280, 720), (1920, 1080), (3840, 2160), (2160, 3840)):
        read_w, read_h, write_w, write_h = kenburns_geometry(*size)
        assert read_w >= write_w and read_h >= write_h


def test_a_portrait_frame_is_budgeted_by_pixels_not_by_width():
    """Scaling a 9:16 frame by a width rule would build an enormous buffer."""
    read_w, read_h, _w, _h = kenburns_geometry(1080, 1920)
    assert read_w * read_h <= 24_000_000 * 1.02


def test_ken_burns_travel_is_written_against_the_frame_count_not_a_step():
    """An incremental `zoom+step` drifts with the frame rate; `on/N` does not.

    A zoom drives the crop's *width* along that sweep — 6530 read pixels down
    to 5830 — rather than ramping the zoom factor, so the picture crosses the
    frame at one speed instead of accelerating, and the width is guaranteed to
    round to a new value every frame. The half pixel keeps `iw/z` off the
    boundary the truncation would otherwise sit on.
    """
    graph = _graph(_shot(_kb(), duration=6.0))          # 6s at 30fps = 180 frames
    assert "z=6530/(6530+0.5-700*on/180)" in graph
    # Two frames past the shot, so `-t` cuts before zoompan restarts its ramp.
    assert "d=182" in graph


def test_zoom_out_starts_wide_and_closes_in_on_one():
    """The same sweep read the other way: it opens from the tightest crop and
    lands on the picture at 1:1."""
    graph = _graph(_shot(_kb("zoom_out"), duration=6.0))
    assert "z=6530/(5830+0.5+700*on/180)" in graph


@pytest.mark.parametrize("effect,swept,pinned", [
    ("pan_right", "x=700*on/180", "y=197"),
    ("pan_left", "x=700*(1-on/180)", "y=197"),
    ("pan_down", "y=394*on/180", "x=350"),
    ("pan_up", "y=394*(1-on/180)", "x=350"),
])
def test_a_pan_holds_the_zoom_and_sweeps_one_axis(effect, swept, pinned):
    """The swept axis is written in the whole read pixels zoompan truncates to,
    and the axis that isn't swept is a number rather than an expression — an
    expression there could round its way onto a different pixel and drift the
    picture sideways through a vertical pan."""
    graph = _graph(_shot(_kb(effect), duration=6.0))
    assert "z=1.1200:" in graph
    assert swept in graph and pinned in graph


def test_no_ken_burns_expression_needs_escaping():
    """A comma or colon in an expression would be read as a filtergraph
    separator, so every expression here is deliberately free of both."""
    chain = F.kenburns_chain("in", "out", width=1920, height=1080, fps=30,
                             duration=6.0, effect="pan_right", amount=0.2)
    zoompan = chain[chain.index("zoompan=") + len("zoompan="):]
    # Only the zoompan call itself — the trailing scale is a separate filter.
    zoompan = zoompan.split(",")[0]
    for option in zoompan.split(":"):
        assert "," not in option


def test_a_cycling_zoom_in_and_out_use_the_same_wave():
    """A shot too long to cross its travel at a pixel a frame rubber-bands A to
    B to A instead of crawling — the same triangle drives both directions, only
    the sign each applies it with differs. It is counted in pixels rather than
    as a fraction because each frame is worth exactly one of them."""
    wave = "(700-abs((on-1400*floor(on/1400))-700))"
    assert f"z=6530/(6530+0.5-{wave})" in _graph(_shot(_kb("zoom_in"), duration=200.0))
    assert f"z=6530/(5830+0.5+{wave})" in _graph(_shot(_kb("zoom_out"), duration=200.0))


def test_a_cycling_pan_still_only_sweeps_one_axis_and_holds_the_zoom():
    right = _graph(_shot(_kb("pan_right"), duration=200.0))
    left = _graph(_shot(_kb("pan_left"), duration=200.0))
    assert "z=1.1200:" in right and "z=1.1200:" in left
    assert "x=(700-abs((on-1400*floor(on/1400))-700))" in right
    # The falling half is the same triangle mirrored, which is just the abs.
    assert "x=abs((on-1400*floor(on/1400))-700)" in left


def test_a_travel_too_small_to_rubber_band_holds_each_pixel_instead():
    """A 2% drift has about seventy read pixels to spend, so a leg at a pixel a
    frame would be over in two and a half seconds and the picture would visibly
    wobble. Under KENBURNS_MIN_LEG_SECONDS the sweep holds each pixel for a
    fixed number of frames and never reverses at all. It still steps — nothing
    can move less than a pixel — but on a cadence that doesn't beat, and it
    crosses 64 of the 68 pixels it centres itself in."""
    graph = _graph(_shot(_kb("pan_up", amount=0.02), duration=15.0))
    assert "y=68-floor(on/7)" in graph


def test_the_hold_cadence_is_the_same_every_time_it_steps():
    """The point of holding rather than rounding a fractional rate: the gaps
    between moves are all equal, so there is no slow beat in them."""
    rects = _zoompan_rects(1920, 1080, seconds=15.0, effect="pan_up", amount=0.02)
    moves = [i for i in range(1, len(rects)) if rects[i] != rects[i - 1]]
    assert len({b - a for a, b in zip(moves, moves[1:])}) == 1


def test_no_ken_burns_expression_needs_escaping_when_cycling():
    """Same invariant as above, for the cycling branch: the wave is built from
    floor/abs and arithmetic only — never ffmpeg's comma-separated mod() — so
    nothing here needs escaping either."""
    chain = F.kenburns_chain("in", "out", width=1920, height=1080, fps=30,
                             duration=600.0, effect="pan_right", amount=0.2)
    zoompan = chain[chain.index("zoompan=") + len("zoompan="):].split(",")[0]
    for option in zoompan.split(":"):
        assert "," not in option


def test_the_zoom_never_travels_further_than_what_was_read():
    """Past that the zoom magnifies pixels rather than revealing them, so a
    wildly over-asked amount closes on the output width and stops there."""
    read_w, _h, _ww, _wh = kenburns_geometry(3840, 2160)
    chain = F.kenburns_chain("in", "out", width=3840, height=2160, fps=30,
                             duration=4.0, effect="zoom_in", amount=5.0)
    assert f"z={read_w}/({read_w}+0.5-{read_w - 3840}*on/120)" in chain


def test_a_video_background_is_never_given_ken_burns():
    """The footage already moves; drifting it as well would fight the content."""
    options = _kb()
    assert F.kenburns_effect_for("video_muted", 0, options) is None
    assert F.kenburns_effect_for("video_sound", 0, options) is None
    assert "zoompan" not in _graph(_shot(options, kind="video_muted"))


def test_cards_hold_still_unless_they_are_opted_in():
    assert F.kenburns_effect_for("card", 0, _kb()) is None
    assert F.kenburns_effect_for("card", 0, _kb(include_cards=True)) == "zoom_in"


def test_an_included_card_zooms_from_the_centre_and_never_pans():
    """A card's text is drawn into the picture, so a pan would walk it out of frame."""
    options = _kb("pan_right", include_cards=True)
    assert F.kenburns_effect_for("card", 0, options) == "zoom_in"
    graph = _graph(_shot(options, kind="card"))
    assert "x=iw/2-(iw/zoom/2)" in graph


def test_alternate_rotates_deterministically_so_a_rerender_matches():
    options = _kb("alternate")
    picks = [F.kenburns_effect_for("still", i, options) for i in range(5)]
    assert picks == ["zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_in"]


def test_a_host_without_zoompan_renders_the_shot_still(monkeypatch):
    monkeypatch.setattr(F, "_filter_cache", frozenset({"overlay"}))
    assert "zoompan" not in _graph(_shot(_kb()))


def test_ken_burns_sits_under_the_overlay_so_the_watermark_stays_pinned():
    argv = F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=6.0,
        output="s.mp4", options=_kb(), preview=False, overlay_png="ov.png", index=0,
    )
    graph = _graph(argv)
    assert graph.index("zoompan") < graph.index("overlay=0:0")


# ── background music ─────────────────────────────────────────────────────────

def _music(**kwargs):
    return MusicSpec(enabled=True, url="/media/u/bed.mp3", **kwargs)


def test_scoring_a_render_never_re_encodes_the_picture():
    """The bed only touches the audio, so the video stream is passed through."""
    argv = F.build_music_command("in.mp4", "bed.mp3", "out.mp4",
                                 duration=40.0, spec=_music(), duck=False)
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert argv[argv.index("-c:a") + 1] == "aac"
    assert argv[argv.index("-map") + 1] == "0:v"


def test_a_short_bed_loops_and_a_long_one_is_cut_to_the_video():
    argv = F.build_music_command("in.mp4", "bed.mp3", "out.mp4",
                                 duration=40.0, spec=_music(), duck=False)
    assert argv[argv.index("-stream_loop") + 1] == "-1"
    assert argv[argv.index("-stream_loop") + 2] == "-i"      # loops the bed, not the video
    assert argv[argv.index("-t") + 1] == "40.000"
    assert "duration=first" in _graph(argv)


def test_the_mix_does_not_let_amix_halve_the_narration():
    """amix normalises by input count by default, which buries the voice."""
    assert "normalize=0" in _graph(
        F.build_music_command("in.mp4", "b.mp3", "o.mp4",
                              duration=40.0, spec=_music(), duck=False))


def test_ducking_compresses_the_bed_against_the_narration():
    graph = _graph(F.build_music_command("in.mp4", "b.mp3", "o.mp4",
                                         duration=40.0, spec=_music(), duck=True))
    # The narration has to be split: it is both the key and part of the mix.
    assert "[0:a]asplit=2[nar][key]" in graph
    assert "[m][key]sidechaincompress=" in graph
    assert "[nar][bed]amix=inputs=2:normalize=0:duration=first[a]" in graph


def test_without_ducking_the_bed_is_mixed_flat():
    graph = _graph(F.build_music_command("in.mp4", "b.mp3", "o.mp4",
                                         duration=40.0, spec=_music(), duck=False))
    assert "sidechaincompress" not in graph
    assert "[0:a][m]amix=inputs=2:normalize=0:duration=first[a]" in graph


def test_the_bed_fades_in_at_the_start_and_out_at_the_end():
    graph = _graph(F.build_music_command(
        "in.mp4", "b.mp3", "o.mp4", duration=40.0,
        spec=_music(fade_in=2.0, fade_out=3.0), duck=False))
    assert "afade=t=in:st=0:d=2.000" in graph
    assert "afade=t=out:st=37.000:d=3.000" in graph


def test_a_video_shorter_than_the_fade_out_still_builds_a_valid_graph():
    graph = _graph(F.build_music_command(
        "in.mp4", "b.mp3", "o.mp4", duration=1.0,
        spec=_music(fade_out=5.0), duck=False))
    assert "afade=t=out:st=0.000:d=5.000" in graph


# ── the finished video's timeline ────────────────────────────────────────────


# ── pauses around headings ───────────────────────────────────────────────────

def _narration(text, paragraph=350, heading=800):
    return chunk_narration(text, paragraph_pause_ms=paragraph, heading_pause_ms=heading)


def test_a_heading_is_held_on_both_sides():
    """A full stop is all a voice has between a paragraph and the heading after
    it, so the two run together in one breath unless real silence is inserted."""
    chunks = _narration("Ends here.\n\nA New Chapter.\n\nBegins now.")
    assert [c.text for c in chunks] == ["Ends here.", "A New Chapter.", "Begins now."]
    assert [c.pause_after_ms for c in chunks] == [800, 800, 0]


def test_prose_without_a_heading_still_travels_as_one_request():
    """Splitting where no pause is wanted would buy nothing and cost a TTS call."""
    chunks = _narration("Just prose. More of the same prose.")
    assert len(chunks) == 1
    assert chunks[0].pause_after_ms == 0


def test_an_ordinary_block_join_is_not_a_break():
    """Blocks are joined with a single newline; only a blank line marks a pause,
    so marking has to be deliberate rather than accidental."""
    chunks = _narration("One paragraph.\nAnother paragraph.")
    assert len(chunks) == 1


def test_turning_the_pause_off_restores_the_old_single_chunk():
    chunks = _narration("Ends here.\n\nA New Chapter.\n\nBegins now.", heading=0)
    assert len(chunks) == 1
    assert chunks[0].pause_after_ms == 0


def test_back_to_back_headings_are_held_once_not_twice():
    chunks = _narration("Body.\n\nFirst Heading.\n\n\nSecond Heading.\n\nMore body.")
    assert [c.text for c in chunks] == [
        "Body.", "First Heading.", "Second Heading.", "More body.",
    ]
    assert [c.pause_after_ms for c in chunks] == [800, 800, 800, 0]


def test_a_long_section_keeps_the_shorter_pause_between_its_own_chunks():
    """Only the gap at a heading is the long one; splitting an oversized section
    is a mechanical necessity, not a place anyone wants a beat."""
    section = " ".join(f"Sentence number {i}." for i in range(400))
    chunks = _narration(f"{section}\n\nA Heading.")
    assert len(chunks) > 2
    assert chunks[-2].pause_after_ms == 800     # the last chunk before the heading
    assert chunks[0].pause_after_ms == 350      # inside the section
    assert chunks[-1].pause_after_ms == 0


def test_nothing_is_held_after_the_final_chunk():
    """A trailing pause would just pad the end of the shot."""
    for text in ("Alone.", "A.\n\nB.", "A.\n\nB.\n\nC."):
        assert _narration(text)[-1].pause_after_ms == 0


def test_blank_narration_produces_no_chunks():
    assert _narration("") == []
    assert _narration("\n\n   \n\n") == []


# ── build_narration_chunks: heading pauses + pause markup, combined ─────────
# This is what synthesize_shot actually calls by default. The markup handling (ellipsis, [pause:...], blank lines) was wired
# in here after users found it had never been reachable at all: RenderOptions
# only ever fed chunk_narration, which has no notion of pause markup.

def _chunks(text, **kwargs):
    opts = RenderOptions(**kwargs)
    return build_narration_chunks(text, options=opts)


def test_a_plain_sentence_period_never_forces_a_split():
    """Unlike the read-aloud player, an ordinary paragraph keeps its natural
    one-breath prosody — only punctuation someone typed on purpose pauses."""
    chunks = _chunks("First sentence. Second sentence. Third sentence.")
    assert len(chunks) == 1
    assert chunks[0].text == "First sentence. Second sentence. Third sentence."


@pytest.mark.parametrize("ellipsis", ["...", "…"])
def test_an_ellipsis_pauses_regardless_of_spelling(ellipsis):
    chunks = _chunks(f"Wait for it{ellipsis} here it comes.")
    assert [c.text for c in chunks] == ["Wait for it" + ellipsis, "here it comes."]
    assert chunks[0].pause_after_ms > 0
    assert chunks[-1].pause_after_ms == 0


def test_an_explicit_pause_marker_is_honoured_and_stripped():
    chunks = _chunks("Then you took a side [pause:1200] really took a side.")
    assert [c.text for c in chunks] == ["Then you took a side", "really took a side."]
    assert chunks[0].pause_after_ms == 1200
    assert "[pause" not in "".join(c.text for c in chunks)


def test_a_heading_boundary_still_pauses_through_pause_markup():
    """The blank line _set_apart wraps a heading in is exactly the "\\n\\n"
    trigger pause_markup already understands — heading_pause_ms drives it."""
    chunks = _chunks("Ends here.\n\nA New Chapter.\n\nBegins now.", heading_pause_ms=2000)
    assert [c.text for c in chunks] == ["Ends here.", "A New Chapter.", "Begins now."]
    assert [c.pause_after_ms for c in chunks] == [2000, 2000, 0]


def test_heading_pause_off_disables_the_blank_line_without_gluing_words():
    """A regression guard: dropping the "\\n\\n" trigger entirely used to also
    drop its whitespace, gluing 'text.Heading' together with no space."""
    chunks = _chunks("Ends here.\n\nA New Chapter.", heading_pause_ms=0)
    assert len(chunks) == 1
    assert chunks[0].text == "Ends here. A New Chapter."


def test_a_long_stretch_with_no_markup_still_falls_back_to_length_splitting():
    """paragraph_pause_ms's one remaining job: a section pause_markup left as
    a single chunk that is still too long for one TTS request."""
    section = " ".join(f"Sentence number {i}." for i in range(400))
    chunks = _chunks(section, paragraph_pause_ms=3000, heading_pause_ms=0)
    assert len(chunks) > 1
    assert chunks[0].pause_after_ms == 3000
    assert chunks[-1].pause_after_ms == 0


def test_blank_narration_produces_no_chunks_via_markup_too():
    assert _chunks("") == []
    assert _chunks("   ") == []


# ── the per-shot timeout scales with the shot, instead of being flat ────────

def test_a_short_shot_gets_the_old_flat_floor():
    assert F.shot_timeout(3.0) == F.SHOT_TIMEOUT_SECONDS
    assert F.shot_timeout(0.0) == F.SHOT_TIMEOUT_SECONDS


def test_a_long_shot_gets_a_budget_scaled_to_its_own_length():
    """A flat cap is wrong because a shot is not a fixed amount of work — an
    eight-minute still and a three-second card used to get the same 900s."""
    assert F.shot_timeout(200.0) == 200.0 * F.SHOT_TIMEOUT_FACTOR


def test_the_exact_shot_that_failed_in_production_now_gets_room_to_finish():
    """Shot 34 from job 3d815257: a 502.678s still that hit the flat 900s cap
    and was killed with 40% of its own length still left to encode."""
    assert F.shot_timeout(502.678) > 900
    assert F.shot_timeout(502.678) >= 502.678 * 2  # comfortable headroom, not just enough


def test_the_timeout_still_has_a_ceiling():
    assert F.shot_timeout(10_000.0) == F.SHOT_TIMEOUT_CEILING


# ── a timeout becomes a readable error, not a severed argv ──────────────────

def test_a_timeout_is_reported_as_a_short_readable_message(monkeypatch):
    """subprocess.TimeoutExpired stringifies as the whole argv followed by the
    reason — over a thousand characters for a real shot command — and the
    worker truncates error_message to 500, which used to cut the reason off
    the end entirely. The message here has to be short enough, on its own, to
    survive that truncation with the reason still in it."""
    def _fake_run(argv, **kwargs):
        raise F.subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 900))
    monkeypatch.setattr(F.subprocess, "run", _fake_run)

    with pytest.raises(F.FFmpegError) as excinfo:
        F.run(["ffmpeg"] + ["-argument"] * 200, timeout=900)

    message = str(excinfo.value)
    assert len(message) < 500
    assert "900" in message


def test_the_original_timeout_is_chained_so_the_full_argv_still_reaches_the_log(monkeypatch):
    def _fake_run(argv, **kwargs):
        raise F.subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 900))
    monkeypatch.setattr(F.subprocess, "run", _fake_run)

    with pytest.raises(F.FFmpegError) as excinfo:
        F.run(["ffmpeg", "-i", "in.mp4", "out.mp4"], timeout=900)
    assert isinstance(excinfo.value.__cause__, F.subprocess.TimeoutExpired)


def test_a_non_zero_exit_is_still_reported_as_before(monkeypatch):
    """The timeout handling must not swallow the ordinary failure path."""
    class _Result:
        returncode = 1
        stderr = b"encoder error: unsupported pixel format"
    monkeypatch.setattr(F.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(F.FFmpegError, match="unsupported pixel format"):
        F.run(["ffmpeg"])


# ── Ken Burns cycles instead of stalling on a shot too long for one sweep ───

def test_a_normal_length_shot_fits_inside_one_leg():
    """A 6s shot at 12% travel is nowhere near long enough to need cycling: a
    leg runs one frame per pixel of travel, and 1080p has 394 of them."""
    rise, _fall = F.kenburns_sweep(394, 6 * 30, 30)
    assert rise == "394*on/180"


def test_the_exact_shot_that_used_to_go_still_now_needs_many_legs():
    """502.678s at 12% travel on a 1080p frame — the shot that used to render
    eight minutes of a static image because one sweep across it would crawl
    under a hundredth of a pixel a frame. It still can't sweep once across its
    own length, so it sweeps a leg it can, many times."""
    rise, _fall = F.kenburns_sweep(394, int(502.678 * 30), 30)
    assert "floor(on/788)" in rise          # a triangle, not a single ramp


def test_raising_travel_lengthens_the_leg():
    """Travel is the discoverable lever: turning it up gives the sweep more
    pixels, and a leg spends one of them a frame, so it runs longer before it
    has to start cycling."""
    read_w, read_h, _w, _h = kenburns_geometry(1920, 1080)
    legs = [read_h - int(read_h / (1 + amount)) for amount in (0.12, 0.40)]
    assert legs[1] > legs[0]
    # And the longer one still sweeps a shot the shorter one would have cycled.
    assert "floor" in F.kenburns_sweep(legs[0], legs[0] + 1, 30)[0]
    assert "floor" not in F.kenburns_sweep(legs[1], legs[0] + 1, 30)[0]


def test_a_degenerate_travel_or_length_still_builds_a_usable_sweep():
    """A zero period would divide by zero building the wave, and a zero frame
    count would divide by zero building the ramp, so both are floored at one."""
    for rise, fall in (F.kenburns_sweep(0, 180, 30), F.kenburns_sweep(394, 0, 30)):
        assert rise and fall
        for expression in (rise, fall):
            assert "/0" not in expression and "," not in expression


def test_the_leg_floor_is_what_picks_the_hold_over_the_rubber_band():
    """Either side of KENBURNS_MIN_LEG_SECONDS, at the same shot length: a
    travel that can sustain a long enough leg rubber-bands, and one that can't
    holds each pixel instead of reversing every second or two."""
    floor_px = int(KENBURNS_MIN_LEG_SECONDS * 30)
    assert "abs" in F.kenburns_sweep(floor_px, 3000, 30)[0]           # cycles
    assert "floor(on/" in F.kenburns_sweep(floor_px - 1, 3000, 30)[0]  # holds


def test_kenburns_effect_for_no_longer_depends_on_shot_length():
    """Ken Burns used to be refused outright on a shot long enough that one
    sweep across it would be too slow to see; kenburns_chain cycles it
    instead now, so which effect a shot gets never depended on duration in
    the first place — the parameter was dropped, not just made optional."""
    options = RenderOptions(ken_burns={"effect": "zoom_in"})
    assert F.kenburns_effect_for("still", 0, options) == "zoom_in"


def test_a_long_shot_cycles_instead_of_stalling():
    """502.678s at 12% travel on a 1920-wide (1080p) frame — the shot that
    used to render eight minutes of a completely still image. It now gets a
    rubber-band cycle: A to B, then B to A, repeating in legs short enough to
    stay visible, instead of one sweep too slow to see or no motion at all."""
    options = RenderOptions(ken_burns={"effect": "zoom_in"})
    argv = F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=502.678,
        output="s.mp4", options=options, preview=False, index=0,
    )
    graph = _graph(argv)
    assert "z=6530/(6530+0.5-(700-abs((on-1400*floor(on/1400))-700)))" in graph
    # It pays the same supersample cost as any other drifting shot now — Ken
    # Burns is no longer refused, so the expense the old gate avoided is back
    # by design.
    read_w, read_h, _w, _h = kenburns_geometry(1920, 1080)
    assert f"scale={read_w}:{read_h}" in graph


def test_a_short_shot_still_gets_the_full_supersampled_drift():
    options = RenderOptions(ken_burns={"effect": "zoom_in"})
    argv = F.build_shot_command(
        kind="still", background="bg.png", audio="n.wav", duration=6.0,
        output="s.mp4", options=options, preview=False, index=0,
    )
    assert "zoompan" in _graph(argv)


# ── the video path never asks the TTS engine to say nothing ───────────────────
# Each of these patterns used to become its own TTS request. The provider
# answered with an empty or error body, which synthesize_shot wrote to a .raw
# file and handed to ffmpeg — which, unable to identify it, fell back to the
# rawvideo demuxer and failed the render with "Invalid pixel format".

@pytest.mark.parametrize("body,label", [
    ("...", "ellipsis beat"),
    ("..", "two dots"),
    (". . .", "spaced dots"),
    ("“...”", "quoted ellipsis"),
    ("---", "rule of dashes"),
    ("\U0001F697", "lone emoji"),
])
def test_a_wordless_paragraph_never_becomes_a_tts_request(body, label):
    chunks = _chunks(f"Before this.\n\n{body}\n\nAfter this.", heading_pause_ms=1600)
    assert [c.text for c in chunks] == ["Before this.", "After this."], label
    # The beat is still a beat — it just lives as silence on the chunk before it.
    assert chunks[0].pause_after_ms > 0


def test_a_shot_of_pure_punctuation_produces_no_chunks_at_all():
    """synthesize_shot already turns an empty chunk list into silence at the
    shot's minimum length, which is the right outcome for a divider slide."""
    assert _chunks("...\n\n---") == []


def test_emoji_are_stripped_from_short_chunks_too():
    """chunk_text strips emoji, but only runs for a chunk too long for one TTS
    request — so relying on it left ordinary chunks with their emoji intact and
    the voice reading them out by description."""
    chunks = _chunks("Drive the car \U0001F697 home.")
    joined = "".join(c.text for c in chunks)
    assert "\U0001F697" not in joined
    assert joined == "Drive the car home."


def test_a_bed_without_a_window_is_not_trimmed_or_delayed():
    graph = _graph(F.build_music_command("in.mp4", "b.mp3", "o.mp4",
                                         duration=40.0, spec=_music(), duck=False))
    assert "atrim" not in graph and "adelay" not in graph and "apad" not in graph


def test_a_bed_windowed_between_an_intro_and_an_outro():
    """It starts after the intro, stops before the outro, and fades at those edges."""
    graph = _graph(F.build_music_command(
        "in.mp4", "b.mp3", "o.mp4", duration=40.0,
        spec=_music(fade_in=2.0, fade_out=3.0), duck=False, start=5.0, end=32.0))
    assert "afade=t=in:st=0:d=2.000" in graph
    # 27 seconds of bed, faded over its own last three.
    assert "afade=t=out:st=24.000:d=3.000" in graph
    assert "atrim=end=27.000,adelay=5000|5000,apad[m]" in graph
    # The output still runs the whole video, intro and outro included.
    argv = F.build_music_command("in.mp4", "b.mp3", "o.mp4", duration=40.0,
                                 spec=_music(), duck=False, start=5.0, end=32.0)
    assert argv[argv.index("-t") + 1] == "40.000"


def test_a_bed_stopping_before_an_outro_needs_no_delay():
    graph = _graph(F.build_music_command(
        "in.mp4", "b.mp3", "o.mp4", duration=40.0,
        spec=_music(fade_out=0.0), duck=True, end=30.0))
    assert "atrim=end=30.000,apad[m]" in graph
    assert "adelay" not in graph
    # Padded rather than ended, so the ducking compressor keeps running.
    assert "[m][key]sidechaincompress=" in graph


def test_a_window_out_of_range_is_clamped_to_the_video():
    graph = _graph(F.build_music_command(
        "in.mp4", "b.mp3", "o.mp4", duration=10.0,
        spec=_music(fade_out=0.0), duck=False, start=12.0, end=50.0))
    # Nothing left to score: a sliver, never a negative trim.
    assert "atrim=end=0.100" in graph


# ── memory: the stitch, the overlays and a preview's drift ──────────────────

def test_a_preview_drift_reads_a_smaller_picture_than_a_full_render():
    """A preview read stills at the same 24 megapixels as 4K, which made a
    drifting preview shot cost four times a still one and was enough, with
    everything else on the box, to get ffmpeg killed for memory."""
    full_w, full_h, _w, _h = kenburns_geometry(854, 480)
    read_w, read_h, write_w, write_h = kenburns_geometry(854, 480, preview=True)
    assert read_w * read_h <= KENBURNS_PREVIEW_READ_PIXELS < full_w * full_h
    assert read_w >= 854 * 4 and read_w >= write_w

    options = _kb()
    argv = F.build_shot_command(kind="still", background="bg.png", audio="n.wav", duration=6.0,
                                output="s.mp4", options=options, preview=True)
    assert f"scale={read_w}:{read_h}" in _graph(argv)


def _blend(n, overlap=0.5):
    return [None] + [("fade", overlap)] * (n - 1)


def test_a_short_stitch_is_one_pass():
    assert F.plan_stitch_chunks([4.0] * 5, _blend(5), 30) == [F.StitchChunk(0, 4)]


def test_a_long_blended_stitch_splits_inside_a_shot_just_before_it_blends_out():
    chunks = F.plan_stitch_chunks([4.0] * 20, _blend(20, 0.6), 30, size=8)
    assert [(c.first, c.last) for c in chunks] == [(0, 7), (7, 14), (14, 19)]
    # Shot 7 blends out at 3.4 s, frame 102: the run stops a frame before it and the
    # next one starts on exactly that frame, so the two together are the whole shot.
    assert chunks[0].end_frame == 101 and chunks[1].start_frame == 101
    assert chunks[-1].end_frame is None


def test_a_stitch_splits_at_a_cut_when_one_comes_first():
    joins = _blend(20)
    joins[9] = None
    chunks = F.plan_stitch_chunks([4.0] * 20, joins, 30, size=8)
    assert chunks[0] == F.StitchChunk(0, 7, 0, 104)
    joins[8] = None
    chunks = F.plan_stitch_chunks([4.0] * 20, joins, 30, size=8)
    assert chunks[0] == F.StitchChunk(0, 7) and chunks[1].first == 8


def test_a_shot_too_short_to_split_moves_the_split_on():
    durations = [4.0] * 20
    durations[7] = 1.0   # blended in and out for 0.5 s each: nothing clear to cut on
    chunks = F.plan_stitch_chunks(durations, _blend(20), 30, size=8)
    assert chunks[0].last == 8 and chunks[1].first == 8


def test_the_runs_cover_every_shot_exactly_once():
    chunks = F.plan_stitch_chunks([3.0] * 61, _blend(61), 30)
    assert chunks[0].first == 0 and chunks[-1].last == 60
    for before, after in zip(chunks, chunks[1:]):
        assert after.first == before.last and after.start_frame == before.end_frame


def test_a_stitch_run_trims_its_ends_by_frame_and_sample_and_decodes_single_threaded():
    argv = F.build_stitch_command(
        ["a.mp4", "b.mp4", "c.mp4"], [4.0, 4.0, 4.0], "out.mp4", joins=_blend(3),
        options=RenderOptions(), preview=True, start_frame=30, end_frame=60)
    graph = _graph(argv)
    assert argv.count("-threads") == 3
    assert "[0:v]trim=start_frame=30,setpts=PTS-STARTPTS,fps=30,settb=AVTB[s0]" in graph
    assert "[0:a]atrim=start_sample=48000,asetpts=PTS-STARTPTS[st0]" in graph
    assert "[2:v]trim=end_frame=60," in graph and "atrim=end_sample=96000" in graph
    # The first shot is 3 s long once trimmed, so the first blend starts at 2.5 s.
    assert "offset=2.500" in graph
    assert "[at2][st2]concat" in graph


def test_each_overlay_layer_is_one_frame_repeated_for_its_window_only():
    """A layer looped as an input for the whole video was decoded on every frame,
    and one started late with `-itsoffset` deadlocked ffmpeg 7.1.5."""
    argv = F.build_overlay_pass(
        "stitched.mp4", [F.TimedLayer("a.png", 1.0, 4.5, 0.3)], "out.mp4",
        options=RenderOptions(), preview=True, duration=10.0)
    assert argv[argv.index("a.png") - 1] == "-i"
    assert "-itsoffset" not in argv and "-loop" not in argv
    assert ("[1:v]format=rgba,loop=loop=-1:size=1,trim=end_frame=105,settb=AVTB,"
            "setpts=N/(30*TB)+1.000/TB,") in _graph(argv)


# ── the partial stitch: only the blends are encoded again ───────────────────

def _keys(*lists):
    return [list(k) for k in lists]


def test_a_blend_is_encoded_from_the_keyframe_before_it_to_the_one_after_it():
    # Two 4 s shots at 30 fps, keyframes every 2 s, blended for 0.5 s.
    pieces = F.plan_partial_stitch([4.0, 4.0], [None, ("fade", 0.5)],
                                   _keys([0, 60], [0, 60]), 30)
    assert pieces == [
        F.StitchPiece(False, 0, 0, 0, 60),     # shot 0 up to its keyframe before 3.5 s
        F.StitchPiece(True, 0, 1, 60, 60),     # the blend, to shot 1's keyframe after 0.5 s
        F.StitchPiece(False, 1, 1, 60, None),  # the rest of shot 1, copied
    ]


def test_a_cut_or_a_dip_needs_nothing_encoded():
    pieces = F.plan_partial_stitch([4.0, 4.0, 4.0], [None, None, None],
                                   _keys([0, 60], [0, 60], [0, 60]), 30)
    assert all(not p.blend and p.end_frame is None for p in pieces) and len(pieces) == 3


def test_a_short_shot_blended_at_both_ends_joins_the_two_blends_into_one():
    # Shot 1 has no keyframe after 0.5 s and before its own blend out at 1.5 s.
    pieces = F.plan_partial_stitch([4.0, 2.0, 4.0], [None, ("fade", 0.5), ("fade", 0.5)],
                                   _keys([0, 60], [0], [0, 60]), 30)
    assert pieces == [
        F.StitchPiece(False, 0, 0, 0, 60),
        F.StitchPiece(True, 0, 2, 60, 60),
        F.StitchPiece(False, 2, 2, 60, None),
    ]


def test_a_blend_into_a_shot_with_no_later_keyframe_runs_to_its_end():
    pieces = F.plan_partial_stitch([4.0, 1.0, 4.0], [None, ("fade", 0.5), None],
                                   _keys([0, 60], [0], [0, 60]), 30)
    assert pieces == [
        F.StitchPiece(False, 0, 0, 0, 60),
        F.StitchPiece(True, 0, 1, 60, None),
        F.StitchPiece(False, 2, 2, 0, None),
    ]


def test_a_shot_whose_only_keyframe_is_its_first_frame_is_blended_from_the_start():
    pieces = F.plan_partial_stitch([2.0, 4.0], [None, ("fade", 0.5)], _keys([0], [0, 60]), 30)
    assert pieces[0] == F.StitchPiece(True, 0, 1, 0, 60)


def test_the_pieces_cover_every_frame_once():
    durations = [4.0, 2.0, 6.0, 3.0, 5.0]
    joins = [None, ("fade", 0.5), ("fade", 0.6), None, ("fade", 0.5)]
    keys = _keys([0, 60], [0], [0, 60, 120], [0, 60], [0, 60, 120])
    pieces = F.plan_partial_stitch(durations, joins, keys, 30)
    for before, after in zip(pieces, pieces[1:]):
        if before.end_frame is None:
            assert after.first == before.last + 1 and after.start_frame == 0
        else:
            assert after.first == before.last and after.start_frame == before.end_frame
    assert pieces[0].start_frame == 0 and pieces[-1].end_frame is None


def test_the_partial_stitch_encodes_the_picture_and_the_sound_apart():
    video = F.build_stitch_command(["a.mp4", "b.mp4"], [4.0, 4.0], "v.mp4",
                                   joins=_blend(2), options=RenderOptions(), preview=True,
                                   start_frame=60, end_frame=60, streams="video")
    assert "-an" in video and "-c:a" not in video and "atrim" not in _graph(video)
    audio = F.build_stitch_command(["a.mp4", "b.mp4"], [4.0, 4.0], "a.m4a",
                                   joins=_blend(2), options=RenderOptions(), preview=True,
                                   streams="audio")
    assert "-vn" in audio and "-c:v" not in audio and "xfade" not in _graph(audio)
    lone = F.build_stitch_command(["a.mp4"], [4.0], "a.m4a", joins=[None],
                                  options=RenderOptions(), preview=True, streams="audio")
    assert "-filter_complex" not in lone and lone[lone.index("-map") + 1] == "0:a"


def test_a_shot_is_cut_half_a_frame_before_each_keyframe():
    argv = F.build_cut_command("s.mp4", "cut_%03d.mp4", [60, 120], 30)
    assert argv[argv.index("-segment_times") + 1] == "1.983333,3.983333"
    assert argv[argv.index("-c") + 1] == "copy" and "-an" in argv


def test_a_blend_piece_seeks_to_its_first_frame_rather_than_decoding_up_to_it():
    argv = F.build_stitch_command(["a.mp4", "b.mp4"], [4.0, 4.0], "v.mp4", joins=_blend(2),
                                  options=RenderOptions(), preview=True,
                                  start_frame=60, end_frame=60, streams="video")
    assert argv[argv.index("a.mp4") - 3:argv.index("a.mp4")] == ["-ss", "1.983333", "-i"]
    assert "[0:v]settb=AVTB[s0]" in _graph(argv) and "trim=end_frame=60" in _graph(argv)
    # Inside one shot, its end is counted from where the seek landed.
    lone = F.build_stitch_command(["a.mp4"], [4.0], "v.mp4", joins=[None],
                                  options=RenderOptions(), preview=True,
                                  start_frame=60, end_frame=90, streams="video")
    assert "[0:v]trim=end_frame=30," in _graph(lone)


# ── clip sound levels and the score during clips (S5) ───────────────────────

def test_a_clip_is_brought_to_the_voices_loudness_then_moved_by_its_own_setting():
    assert F.clip_gain(-30.0, -18.0) == 12.0
    assert F.clip_gain(-10.0, -18.0) == -8.0
    assert F.clip_gain(-30.0, -18.0, adjust_db=-6.0) == 6.0
    # Silence (unmeasurable) is left alone, but still follows its own setting.
    assert F.clip_gain(None, -18.0) == 0.0 and F.clip_gain(None, -18.0, 3.0) == 3.0
    # A near-silent clip is not raised without limit: that would only raise the noise.
    assert F.clip_gain(-70.0, -16.0) == F.CLIP_GAIN_LIMITS_DB[1]


def test_the_voices_loudness_is_its_pieces_averaged_by_energy_and_time():
    assert F.combined_loudness([(-18.0, 10.0), (-18.0, 30.0)]) == pytest.approx(-18.0)
    # Twice the time at one level weighs twice as much; levels add as energy, not dB.
    assert F.combined_loudness([(-20.0, 10.0), (-10.0, 10.0)]) == pytest.approx(-12.6, abs=0.1)
    assert F.combined_loudness([]) is None


def test_a_raised_clip_is_limited_and_a_lowered_one_is_not():
    def audio(gain):
        argv = F.build_shot_command(
            kind="video_sound", background="clip.mp4", audio=None, duration=6.0,
            output="s.mp4", options=RenderOptions(), preview=True,
            background_has_audio=True, audio_gain_db=gain)
        return [c for c in _graph(argv).split(";") if c.endswith("[a]")][0]
    assert "volume=12.0dB,alimiter=limit=0.891:level=0:latency=1,apad" in audio(12.0)
    assert "volume=-8.0dB,apad" in audio(-8.0) and "alimiter" not in audio(-8.0)
    assert "volume" not in audio(0.0)


def test_a_track_can_leave_for_clips_and_come_back_after():
    track = F.MixTrack(path="m.mp3", start=0.0, length=30.0, during_clips="mute")
    graph = _graph(F.build_mix_command("in.mp4", [track], "o.mp4", duration=30.0,
                                       clip_windows=[(8.0, 15.0)]))
    assert ("volume='(1-max(0,min(1,min((t-7.400)/0.600,(15.600-t)/0.600))))':eval=frame"
            in graph)
    # Still ducked under the narration as before.
    assert "[t1][key]sidechaincompress=" in graph


def test_a_track_can_play_on_through_clips_and_still_duck_under_the_voice():
    plain = F.MixTrack(path="a.mp3", start=0.0, length=30.0)
    spared = F.MixTrack(path="b.mp3", start=0.0, length=30.0, during_clips="play")
    graph = _graph(F.build_mix_command("in.mp4", [plain, spared], "o.mp4", duration=30.0,
                                       clip_windows=[(8.0, 15.0)]))
    assert "[0:a]asplit=3[nar][key][keyvoice]" in graph
    assert "[keyvoice]volume='" in graph and "[keyspared]" in graph
    assert "[t1][key]sidechaincompress=" in graph
    assert "[t2][keyspared]sidechaincompress=" in graph
    assert "[nar][bed][spared]amix=inputs=3" in graph
    # Alone, it needs no key for a bed that isn't there.
    alone = _graph(F.build_mix_command("in.mp4", [spared], "o.mp4", duration=30.0,
                                       clip_windows=[(8.0, 15.0)]))
    assert "[0:a]asplit=2[nar][keyvoice]" in alone


def test_without_clips_a_tracks_choice_during_clips_changes_nothing():
    for mode in ("mute", "play"):
        graph = _graph(F.build_mix_command(
            "in.mp4", [F.MixTrack(path="m.mp3", start=0.0, length=30.0, during_clips=mode)],
            "o.mp4", duration=30.0))
        assert "eval=frame" not in graph and "[t1][key]sidechaincompress=" in graph


def test_a_wave_window_reads_a_slice_of_the_videos_own_sound_and_fades_with_its_scrim():
    wave = F.TimedWave(RenderOptions().waveform, 2.0, 6.0, 0.5)
    argv = F.build_overlay_pass(
        "stitched.mp4", [], "out.mp4", options=RenderOptions(), preview=True,
        duration=10.0, waves=[wave], width=1280, height=720)
    graph = _graph(argv)
    assert "[0:a]anull[wa1]" in graph
    assert "atrim=start=2.000:end=6.000" in graph and "showwaves=s=1280x158" in graph
    # The scrim and the wave are one stream, so the fade takes both.
    assert "overlay=format=auto:shortest=1[wv1_b]" in graph
    assert "fade=t=in:st=2.000:d=0.500:alpha=1" in graph
    assert "overlay=0:562:eof_action=pass:enable='between(t,2.000,6.000)'[wv1]" in graph
    assert argv[argv.index("-map") + 1] == "[wv1]"
    assert argv[argv.index("-c:a") + 1] == "copy"


def test_several_waves_split_the_sound_once():
    waves = [F.TimedWave(RenderOptions().waveform, 0.0, 2.0), F.TimedWave(RenderOptions().waveform, 3.0, 5.0)]
    graph = _graph(F.build_overlay_pass(
        "s.mp4", [], "o.mp4", options=RenderOptions(), preview=True, duration=6.0,
        waves=waves, width=1280, height=720))
    assert "[0:a]asplit=2[wa1][wa2]" in graph
    # The second wave is drawn over the first, not over the bare picture.
    assert "[wv1][wv2_p]overlay=" in graph


@pytest.mark.skipif(not os.path.exists("/usr/bin/ffmpeg") or "showwaves" not in F.available_filters(),
                    reason="needs ffmpeg with showwaves")
def test_the_wave_pass_really_runs_and_draws_only_in_its_window(tmp_path):
    source = tmp_path / "in.mp4"
    F.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=30:d=4",
           "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
          timeout=60)
    wave = F.TimedWave(RenderOptions().waveform, 1.0, 3.0, 0.2)
    argv = F.build_overlay_pass(str(source), [], str(tmp_path / "out.mp4"),
                                options=RenderOptions(), preview=True, duration=4.0,
                                waves=[wave], width=320, height=180)
    F.run(argv, timeout=120)

    def green_at(t):
        png = tmp_path / f"f{t}.png"
        F.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t),
               "-i", str(tmp_path / "out.mp4"), "-frames:v", "1", str(png)], timeout=30)
        from PIL import Image
        img = Image.open(png).convert("RGB")
        return any(g > 150 and r < 100 for r, g, _ in img.getdata())

    assert green_at(2.0) and not green_at(0.5) and not green_at(3.6)
