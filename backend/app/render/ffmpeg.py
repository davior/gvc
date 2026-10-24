"""ffmpeg/ffprobe argv builders and process helpers.

Every builder is a pure function returning a `list[str]`, so the filtergraphs can
be asserted in unit tests without running ffmpeg — the same approach the repo
already takes for the URL importer's parsers.

The one invariant the whole pipeline rests on: every shot is encoded with
byte-identical codec parameters (see `encode_args`), which is what lets the final
stitch be a `concat -c copy` remux instead of a second full encode. A stray SAR
or pixel format is the usual way that silently breaks, so every video chain ends
with `setsar=1,format=yuv420p`.
"""

import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.render.options import (
    DIP_TRANSITIONS, KENBURNS_MIN_LEG_SECONDS, XFADE_NAMES, MusicSpec, TransitionSpec,
    RenderOptions, encoder_tier, frame_size, is_crossfade, kenburns_geometry,
    transition_colour,
)

logger = logging.getLogger(__name__)

# Long enough for a 4K encode of a multi-minute clip, short enough that a wedged
# process can't hold the render queue forever. Mirrors transcription.py's style.
# A flat per-shot cap is wrong, because a shot is not a fixed amount of work: a
# three-second card and an eight-minute still both used to get 900 seconds, and
# the second one cannot possibly finish in it. These bound a shot by how long it
# actually is, with the old value as the floor so short shots are unaffected.
SHOT_TIMEOUT_SECONDS = 900
SHOT_TIMEOUT_FACTOR = 6
SHOT_TIMEOUT_CEILING = 2 * 60 * 60
PROBE_TIMEOUT_SECONDS = 30

# An xfade stitch puts every shot in one filtergraph as its own input. That is
# fine for the ten to thirty shots a normal article produces and absurd at the
# 200 VIDEO_MAX_SHOTS ceiling, so past this many the render degrades to a plain
# concat rather than building a graph that would thrash the box.
XFADE_MAX_SHOTS = 60

# An overlap shorter than this isn't a transition, it's a glitch.
MIN_TRANSITION_SECONDS = 0.05

# Deterministic rotation for the "alternate" Ken Burns effect. Keyed off the shot
# index rather than a random draw so re-rendering a note is reproducible.
KENBURNS_CYCLE = ("zoom_in", "pan_right", "zoom_out", "pan_left")


class FFmpegError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


_filter_cache: Optional[frozenset] = None


def available_filters() -> frozenset:
    """Filters this ffmpeg build actually has, probed once and cached.

    Debian's build carries everything we use, but a slimmer base image might not,
    and discovering that four minutes into a render is a bad way to find out.
    Callers degrade (waveform off, burn-in falls back to a sidecar) instead.
    """
    global _filter_cache
    if _filter_cache is not None:
        return _filter_cache
    names = set()
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, timeout=PROBE_TIMEOUT_SECONDS)
        for line in out.stdout.decode(errors="replace").splitlines():
            parts = line.split()
            # Rows look like: " T.. showwaves  A->V  Convert input audio to ..."
            if len(parts) >= 3 and not line.startswith("Filters:"):
                names.add(parts[1])
    except Exception as exc:
        logger.warning("Could not probe ffmpeg filters: %s", exc)
    _filter_cache = frozenset(names)
    return _filter_cache


def shot_timeout(duration: float) -> int:
    """How long one shot may take to encode, given how long the shot is.

    Encoding runs slower than real time once a filter chain and a slow x264
    preset are involved, so the budget is a multiple of the shot's length rather
    than a constant — with the old flat value as a floor, so nothing short gets
    less than it had.
    """
    scaled = max(0.0, duration) * SHOT_TIMEOUT_FACTOR
    return int(min(SHOT_TIMEOUT_CEILING, max(SHOT_TIMEOUT_SECONDS, scaled)))


def run(argv: Sequence[str], *, cwd: Optional[str] = None, timeout: int = SHOT_TIMEOUT_SECONDS) -> None:
    """Run ffmpeg, raising FFmpegError with something readable on failure.

    A timeout is converted here rather than left to propagate. `TimeoutExpired`
    stringifies as the entire argv followed by the reason, which runs past a
    thousand characters — so by the time the worker truncates it for the UI the
    reason has been cut off the end and all the user sees is a severed command
    line. The original is chained, so the full argv still reaches the log, which
    is where it is actually useful.
    """
    try:
        result = subprocess.run(list(argv), capture_output=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(
            f"ffmpeg gave up on a segment after {timeout}s. It is probably a very "
            f"long section on one image — try a lower resolution or a faster "
            f"encoding preset."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        tail = stderr[-800:].strip()
        code = result.returncode
        # `-loglevel error` means a process killed from outside says nothing at
        # all, so the exit status is the only clue that it was the OOM killer.
        if code < 0:
            reason = f"killed by signal {-code}"
            if code == -9:
                reason += " (most likely out of memory)"
        else:
            reason = f"exit code {code}"
        logger.error("ffmpeg %s\nargv: %s\nstderr: %s", reason, " ".join(argv), stderr or "<empty>")
        raise FFmpegError(f"ffmpeg failed ({reason}): {tail}".rstrip(": "))


def probe_duration(path: str) -> float:
    """Container duration in seconds, or 0.0 if it can't be read."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, timeout=PROBE_TIMEOUT_SECONDS,
        )
        return float((out.stdout.decode(errors="replace").strip() or "0") or 0)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def probe_has_audio(path: str) -> bool:
    """True when the file carries at least one audio stream.

    This is the test that decides whether a clip plays with its own sound (and
    pauses the narration) or is looped silently as a background.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, timeout=PROBE_TIMEOUT_SECONDS,
        )
        return "audio" in out.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False


# Spoken word sits about here; used as the target when a video has no narration.
DEFAULT_LOUDNESS_LUFS = -16.0
# A clip quieter than this is silence or room tone, and matching it to the voice
# would only raise the noise.
SILENT_LUFS = -60.0
CLIP_GAIN_LIMITS_DB = (-30.0, 24.0)


def measure_loudness(path: str, length: Optional[float] = None) -> Optional[float]:
    """Integrated loudness (EBU R128, LUFS) of a file's sound, or of its first
    `length` seconds; None when it has none worth measuring."""
    argv = ["ffmpeg", "-hide_banner", "-nostats", "-i", path]
    if length is not None:
        argv += ["-t", f"{max(0.1, length):.3f}"]
    argv += ["-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    try:
        out = subprocess.run(argv, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS * 10)
    except (OSError, subprocess.SubprocessError):
        return None
    # The summary comes last; its "I:" line is the integrated loudness.
    found = None
    for line in out.stderr.decode(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("I:") and line.endswith("LUFS"):
            try:
                found = float(line[2:-4])
            except ValueError:
                found = None
    if found is None or found < SILENT_LUFS:
        return None
    return found


def combined_loudness(levels: Sequence[Tuple[float, float]]) -> Optional[float]:
    """The loudness of several pieces played one after another, from each one's
    (LUFS, seconds): their energy averaged by time, as R128 would over the whole."""
    weighted = [(10 ** (lufs / 10), seconds) for lufs, seconds in levels if seconds > 0]
    total = sum(seconds for _, seconds in weighted)
    if not weighted or total <= 0:
        return None
    return 10 * math.log10(sum(energy * seconds for energy, seconds in weighted) / total)


def clip_gain(clip_lufs: Optional[float], target_lufs: float, adjust_db: float = 0.0) -> float:
    """dB to bring a clip to the narration's loudness, then move it by `adjust_db`."""
    match = 0.0 if clip_lufs is None else target_lufs - clip_lufs
    low, high = CLIP_GAIN_LIMITS_DB
    return max(low, min(high, match + adjust_db))


def encode_args(options: RenderOptions, preview: bool) -> List[str]:
    """Codec flags shared by every shot. Identical output = concat can `-c copy`."""
    preset, crf = encoder_tier(options.quality, preview)
    fps = options.fps
    return [
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-r", str(fps), "-g", str(fps * 2), "-keyint_min", str(fps),
        "-video_track_timescale", "90000",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-max_muxing_queue_size", "1024",
    ]


def _hex_to_ffmpeg(colour: str) -> str:
    """'#00FF41' -> '0x00FF41'. Falls back to white on anything unparseable."""
    c = (colour or "").strip().lstrip("#")
    if len(c) == 8:  # RGBA from a colour picker — drop the alpha, we set it separately
        c = c[:6]
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in c):
        return "0xffffff"
    return f"0x{c.lower()}"


def fit_chain(src: str, out: str, width: int, height: int, fit: str) -> str:
    """Scale arbitrary media into the output frame.

    blur — a scaled-up, blurred copy fills the frame with the real media
           contained and centred on top. Never crops, and reads as deliberate at
           every aspect ratio, which matters most for 9:16 where article images
           are almost always the wrong shape.
    pad  — letterbox against black.
    crop — fill the frame and lose the edges.
    """
    if fit == "crop":
        return (f"[{src}]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1[{out}]")
    if fit == "pad":
        return (f"[{src}]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{out}]")
    sigma = max(8, width // 40)
    return (
        f"[{src}]split[{out}_a][{out}_b];"
        f"[{out}_a]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={sigma},eq=brightness=-0.08[{out}_bg];"
        f"[{out}_b]scale={width}:{height}:force_original_aspect_ratio=decrease[{out}_fg];"
        f"[{out}_bg][{out}_fg]overlay=(W-w)/2:(H-h)/2:shortest=1,setsar=1[{out}]"
    )


def wave_band(height: int, spec) -> "tuple[int, int]":
    """The wave's band as (height, top edge) in pixels, from its percentage and position."""
    band = max(24, int(height * max(5, min(60, spec.height_pct)) / 100))
    band -= band % 2
    if spec.position == "top":
        y = 0
    elif spec.position == "center":
        y = (height - band) // 2
    else:
        y = height - band
    return band, y


def waveform_chain(
    audio_src: str, video_src: str, out: str,
    width: int, height: int, fps: int, spec,
) -> str:
    """Animated showwaves band composited over the background.

    Two details matter: `rate` must equal the output frame rate or the wave
    drifts against the picture, and the alpha is set once — the reference
    formula's repeated colorchannelmixer passes collapse to a single value.
    """
    band, y = wave_band(height, spec)
    alpha = max(0.05, min(1.0, spec.opacity))
    colour = _hex_to_ffmpeg(spec.color)

    parts = [
        f"[{audio_src}]aformat=channel_layouts=mono,"
        f"showwaves=s={width}x{band}:mode={spec.mode}:draw=full:scale=sqrt:"
        f"rate={fps}:colors={colour},format=rgba,"
        f"colorchannelmixer=aa={alpha}[{out}_w]"
    ]
    base = video_src
    scrim = max(0.0, min(1.0, spec.scrim))
    if scrim > 0.01:
        parts.append(
            f"[{base}]drawbox=x=0:y={y}:w={width}:h={band}:"
            f"color=black@{scrim}:t=fill[{out}_s]"
        )
        base = f"{out}_s"
    parts.append(f"[{base}][{out}_w]overlay=0:{y}[{out}]")
    return ";".join(parts)


def _even(value: float) -> int:
    """Round down to an even integer — libx264 with yuv420p requires it."""
    n = max(2, int(value))
    return n - n % 2


def kenburns_effect_for(kind: str, index: int, options: RenderOptions) -> Optional[str]:
    """Which drift, if any, this shot gets.

    A video background already moves, so only stills and (opt-in) cards drift. A
    card has its text drawn into the picture, so it is only ever allowed to zoom
    from the centre — a pan would walk the type out of frame.

    Every qualifying shot gets its drift regardless of how long it runs — a shot
    long enough that one sweep across it would be too slow to see gets the drift
    cycled by `kenburns_sweep` instead of dropped.
    """
    effect = options.ken_burns.effect
    if effect == "none":
        return None
    if kind == "card":
        if not options.ken_burns.include_cards:
            return None
    elif kind != "still":
        return None

    if effect == "alternate":
        effect = KENBURNS_CYCLE[index % len(KENBURNS_CYCLE)]
    if kind == "card" and effect.startswith("pan"):
        return "zoom_in"
    return effect


def kenburns_sweep(travel: int, frames: int, fps: int) -> Tuple[str, str]:
    """(rising, falling) crop-origin expressions, in whole read pixels.

    `travel` is the headroom zoompan will clamp the origin against, counted in
    the very pixels it truncates to, and `frames` is the length of the shot.
    Both expressions run between 0 and `travel`, one upwards and one down, and
    every effect is built out of that pair.

    The invariant this exists to hold: **the truncated origin has to land on a
    different pixel from one frame to the next.** A pan holds its zoom, so the
    crop is the same size on every frame — an origin that rounds to the value it
    had last frame makes zoompan emit a picture identical to the one before it,
    and at less than a pixel a frame that happens on half of them. Those
    duplicates are the stutter. They are also not evenly spread: which frames
    repeat is decided by the fractional part of the rate, so the freezes cluster
    and thin out on a slow beat against the frame rate — a 16-24 second section
    at the default 12% drift beat about every two seconds, which is what "it
    pauses every so often" was.

    So the rate is never allowed below a pixel a frame:

    fast enough   one sweep across the whole travel, `travel*on/frames`, which
                  advances one pixel or two on every frame and repeats none;
    too slow      the sweep rubber-bands, A to B to A, across `travel` frames —
                  exactly a pixel a frame, the slowest this can go, and the only
                  perfectly even rate available;
    slower still  when even that leg would be over in a few seconds — only a
                  very small `amount` has that little travel — reversing that
                  often would read as a wobble, so the sweep holds each pixel
                  for a fixed number of frames instead. It still steps, but on a
                  cadence that never beats, and it crosses nearly all of the
                  travel without reversing at all.

    No expression here contains a comma or a colon, which is what keeps the
    filtergraph free of any escaping: `on mod period` is written out as `on -
    period*floor(on/period)` and the triangle's peak with `abs`, because
    ffmpeg's own `mod()` and `min()` take comma-separated arguments.
    """
    travel, frames = max(1, travel), max(1, frames)
    if frames <= travel:
        return f"{travel}*on/{frames}", f"{travel}*(1-on/{frames})"

    if travel >= KENBURNS_MIN_LEG_SECONDS * max(1, fps):
        # A triangle of period 2*travel, counted in pixels because each frame is
        # worth exactly one: 0 at on=0, `travel` at on=travel, back to 0 at
        # on=2*travel, repeating.
        period = 2 * travel
        phase = f"(on-{period}*floor(on/{period}))"
        return f"({travel}-abs({phase}-{travel}))", f"abs({phase}-{travel})"

    hold = -(-frames // travel)          # ceil: frames spent on each pixel
    used = min(travel, frames // hold)
    lead = (travel - used) // 2          # centre the short sweep in its headroom
    tick = f"floor(on/{hold})"
    return (f"{lead}+{tick}" if lead else tick), f"{lead + used}-{tick}"


def kenburns_chain(
    src: str, out: str, *,
    width: int, height: int, fps: int, duration: float,
    effect: str, amount: float, preview: bool = False,
) -> str:
    """A `zoompan` drift over a still, rendered above `width`x`height` and scaled back.

    `width`/`height` are the output frame; the caller must have fitted the source
    at `kenburns_geometry`'s read size, which is what makes this smooth. zoompan
    truncates its crop origin to whole pixels of the frame it is given, so
    reading a much larger picture, and writing one larger than the frame before
    scaling down, are what turn a whole-pixel step into a third of one.

    Everything below is therefore worked out in those same whole read pixels
    rather than in fractions of the frame: the crop zoompan will take, the
    headroom left over, and the sweep across it. `kenburns_sweep` holds the rule
    that keeps it gliding — never less than one of those pixels per frame.

    A zoom drives the crop's *width* along that sweep rather than the zoom
    factor, and `z` is written as the ratio that produces it. Ramping `z`
    linearly instead would accelerate the picture across the shot (the crop is
    `iw/z`, not `z`), and would leave the width free to round to the same value
    twice running, which on a zoom is the same duplicate frame a pan gets. The
    half pixel in the divisor puts `iw/z` at the middle of the intended width
    rather than on its boundary, so the truncation can't be tipped either way by
    the last bit of the division.

    `zoompan` restarts its ramp every `d` output frames while `-loop 1` feeds
    frames forever, so `d` is set a couple of frames beyond the shot and the
    caller's `-t` cuts before the ramp can begin again.
    """
    read_width, read_height, write_width, write_height = kenburns_geometry(width, height, preview)
    frames = max(1, int(math.ceil(max(0.1, duration) * max(1, fps))))
    # What is read is the only headroom the zoom has; travelling past it would
    # start magnifying pixels, which is the softness this arrangement avoids.
    span = max(0.01, min(amount, read_width / max(1, width) - 1.0))
    # Rounded to the text ffmpeg will parse and read back, so the crop worked
    # out here is the crop ffmpeg computes, to the pixel.
    zoom_text = f"{1.0 + span:.4f}"
    zoom = float(zoom_text)

    # Exactly what zoompan will do: crop int(iw/zoom) x int(ih/zoom), and clamp
    # the origin to whatever is left of the frame.
    crop_width = max(1, int(read_width / zoom))
    crop_height = max(1, int(read_height / zoom))
    vertical = effect in ("pan_up", "pan_down")
    travel = max(1, (read_height - crop_height) if vertical
                 else (read_width - crop_width))
    rise, fall = kenburns_sweep(travel, frames, fps)

    if effect == "zoom_out":
        # Opens out from the tightest crop and lands on the picture 1:1.
        z = f"{read_width}/({crop_width}+0.5+{rise})"
    elif effect.startswith("pan"):
        z = zoom_text
    else:  # zoom_in and anything unrecognised
        z = f"{read_width}/({read_width}+0.5-{rise})"

    # A pan sweeps one axis end to end and pins the other dead centre — as a
    # number, not an expression, so nothing on it can move at all. A zoom has no
    # axis to sweep and stays centred on both, which it can only do against the
    # crop it is about to take.
    if effect == "pan_left":
        x, y = fall, str((read_height - crop_height) // 2)
    elif effect == "pan_right":
        x, y = rise, str((read_height - crop_height) // 2)
    elif effect == "pan_up":
        x, y = str((read_width - crop_width) // 2), fall
    elif effect == "pan_down":
        x, y = str((read_width - crop_width) // 2), rise
    else:
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    chain = (f"[{src}]zoompan=z={z}:x={x}:y={y}:"
             f"d={frames + 2}:s={write_width}x{write_height}:fps={fps}")
    if (write_width, write_height) != (width, height):
        # Scaling back down halves whatever step survived and averages it away.
        chain += f",scale={width}:{height}"
    return f"{chain}[{out}]"


def dip_seconds(style: str, requested: float, shot_duration: float) -> float:
    """How long a dip-through-colour transition may last on a shot this short.

    A shot has to hold a fade out as well as a fade in, so a third of its length
    is the ceiling; below that the two would overlap and the picture would never
    be fully visible.
    """
    if style not in DIP_TRANSITIONS:
        return 0.0
    seconds = min(max(0.0, requested), max(0.0, shot_duration) / 3.0)
    return seconds if seconds >= MIN_TRANSITION_SECONDS else 0.0


def crossfade_overlap(
    style: str, durations: Sequence[float], requested: float,
    *, filters: Optional[frozenset] = None,
) -> Optional[float]:
    """The overlap an xfade stitch should use, or None to fall back to concat.

    Every reason a crossfade can't run lives here so the renderer branches once
    and the guards can be tested without ffmpeg: the style isn't a blend, there
    is nothing to blend between, the graph would be unreasonably large, the host
    ffmpeg lacks the filters, or the shots are too short to absorb an overlap.
    """
    if not is_crossfade(style) or len(durations) < 2:
        return None
    if len(durations) > XFADE_MAX_SHOTS:
        return None
    names = available_filters() if filters is None else filters
    if "xfade" not in names or "concat" not in names:
        return None
    overlap = min(max(0.0, requested), 0.5 * min(durations))
    return overlap if overlap >= MIN_TRANSITION_SECONDS else None


def build_shot_command(
    *,
    kind: str,
    background: Optional[str],
    audio: Optional[str],
    duration: float,
    output: str,
    options: RenderOptions,
    preview: bool,
    overlay_png: Optional[str] = None,
    subtitle_file: Optional[str] = None,
    background_has_audio: bool = False,
    index: int = 0,
    dip_in: bool = True,
    dip_out: bool = True,
    in_transition: Optional[TransitionSpec] = None,
    out_transition: Optional[TransitionSpec] = None,
    loop: bool = True,
    path: Optional["KenBurnsPath"] = None,
    audio_gain_db: float = 0.0,
) -> List[str]:
    """Full argv for rendering one shot to its own MP4.

    Paths are expected to be relative to the working directory the caller runs
    this in, which keeps the `subtitles=` filter free of any escaping.
    `dip_in`/`dip_out` False leave a dip transition off that end of the shot,
    where it joins a neighbour by a straight cut (see `Shot.cut_in`).

    GVC additions, all defaulting to Notes' behaviour:
    - `in_transition` / `out_transition`: the join at each end, which in GVC differ
      per scene (a scene's `transition_in` is its incoming join and the previous
      scene's outgoing one). Unset, both are `options.transition`.
    - `loop` False on a video holds its last frame instead of repeating it.
    - `path`: a Ken Burns move between two frames of the picture (S1), in place of
      the preset drift.
    - `audio_gain_db`: a clip's own sound brought to the narration's loudness (S5).
    """
    width, height = frame_size(options.aspect, options.resolution, preview)
    argv: List[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # ── inputs ────────────────────────────────────────────────────────────────
    if kind in ("still", "card"):
        argv += ["-loop", "1", "-framerate", str(options.fps), "-i", background or ""]
    elif kind == "video_muted":
        # Loop the clip for as long as the narration runs, and cut the moment it
        # ends — the two halves of the spec's rule fall out of these flags.
        if loop:
            argv += ["-stream_loop", "-1"]
        argv += ["-i", background or ""]
    else:  # video_sound
        argv += ["-i", background or ""]

    video_in = "0:v"
    audio_in: Optional[str] = None
    next_index = 1

    if kind == "video_sound":
        if background_has_audio:
            audio_in = "0:a"
        else:
            argv += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            audio_in = f"{next_index}:a"
            next_index += 1
    else:
        argv += ["-i", audio or ""]
        audio_in = f"{next_index}:a"
        next_index += 1

    overlay_index: Optional[int] = None
    if overlay_png:
        argv += ["-i", overlay_png]
        overlay_index = next_index
        next_index += 1

    # ── filtergraph ───────────────────────────────────────────────────────────
    filters = available_filters()

    # A drifting shot is fitted larger than the output frame so `zoompan` has
    # real pixels to zoom into, and zoompan's own `s=` brings it back down.
    # Fitting at the output size first would just magnify its softness.
    drift = (kenburns_effect_for(kind, index, options)
             if "zoompan" in filters and path is None else None)
    if path is not None and kind == "still" and "zoompan" in filters:
        read_width, read_height, _w, _h = kenburns_geometry(width, height, preview)
        # A path's frames are fractions of the *picture*, so the picture is placed
        # whole on a canvas of the output's shape (never cropped, whatever `fit`
        # says) and the frames are worked out on that canvas.
        chains = [fit_chain(video_in, "fit", read_width, read_height,
                            "pad" if options.fit == "pad" else "blur")]
        chains.append(kenburns_path_chain(
            "fit", "kb", width=width, height=height, fps=options.fps, duration=duration,
            path=path, preview=preview,
        ))
        stage = "kb"
    elif drift:
        read_width, read_height, _w, _h = kenburns_geometry(width, height, preview)
        chains = [fit_chain(video_in, "fit", read_width, read_height, options.fit)]
        chains.append(kenburns_chain(
            "fit", "kb", width=width, height=height, fps=options.fps, duration=duration,
            effect=drift, amount=options.ken_burns.amount, preview=preview,
        ))
        stage = "kb"
    else:
        chains = [fit_chain(video_in, "fit", width, height, options.fit)]
        stage = "fit"

    if kind in ("video_muted", "video_sound") and not loop:
        # Shorter than its scene and not to be repeated: hold the last frame. A clip
        # with its sound reaches here when a blend out of it asks for more than the
        # file has left after its out point (`compile.layout`'s tail).
        chains.append(f"[{stage}]tpad=stop_mode=clone:stop_duration={duration:.3f}[hold]")
        stage = "hold"

    draw_wave = bool(options.waveform.enabled and audio_in and "showwaves" in filters)

    # An input pad may only be consumed once in a filtergraph, and the waveform
    # reads the same track that gets muxed, so it needs an explicit asplit.
    audio_main = audio_in
    if draw_wave:
        chains.append(f"[{audio_in}]asplit=2[a_wave][a_main]")
        audio_main = "a_main"
        chains.append(waveform_chain("a_wave", stage, "wv", width, height, options.fps, options.waveform))
        stage = "wv"

    if overlay_index is not None:
        chains.append(f"[{stage}][{overlay_index}:v]overlay=0:0[ov]")
        stage = "ov"

    if subtitle_file and "subtitles" in filters:
        chains.append(f"[{stage}]subtitles={subtitle_file}[sub]")
        stage = "sub"

    # A dip through black or white is drawn inside the shot, so its duration is
    # unchanged and the stitch stays a `concat -c copy` remux. A blending
    # transition cannot be expressed here at all — see build_xfade_command.
    entering = in_transition or options.transition
    leaving = out_transition or options.transition
    dip_start = dip_seconds(entering.style, entering.duration, duration) if dip_in else 0.0
    dip = dip_seconds(leaving.style, leaving.duration, duration) if dip_out else 0.0
    fades = []
    if dip_start > 0:
        fades.append(f"fade=t=in:st=0:d={dip_start:.3f}:color={transition_colour(entering.style)}")
    if dip > 0:
        fades.append(f"fade=t=out:st={duration - dip:.3f}:d={dip:.3f}:color={transition_colour(leaving.style)}")
    if fades:
        chains.append(f"[{stage}]{','.join(fades)}[fd]")
        stage = "fd"

    chains.append(f"[{stage}]setsar=1,format=yuv420p[v]")

    # Pad the audio so a shot always reaches its target length even when the
    # narration is shorter (a media block with little text under it).
    audio_chain = f"[{audio_main}]aresample=48000,aformat=channel_layouts=stereo"
    if abs(audio_gain_db) >= 0.05:
        audio_chain += f",volume={audio_gain_db:.1f}dB"
        if audio_gain_db > 0:
            # Raising a quiet clip can push its loudest moments past full scale, so
            # they are limited at -1 dBFS rather than clipped. `level=0` stops the
            # limiter normalising the whole clip again, and `latency` takes back
            # the few milliseconds its lookahead would put between sound and picture.
            audio_chain += ",alimiter=limit=0.891:level=0:latency=1"
    audio_chain += ",apad"
    if dip > 0:
        # Only the tail is faded, to match the picture dipping to colour there —
        # and it lands in the trailing hold `shot_end_pause_ms` leaves after the
        # last word, not on speech itself. The start has no equivalent lead-in
        # silence: narration begins at st=0 of the shot, so a matching fade-in
        # there was ramping up through the sentence's actual first word,
        # sometimes past the point of being audible at all.
        audio_chain += f",afade=t=out:st={duration - dip:.3f}:d={dip:.3f}"
    chains.append(f"{audio_chain}[a]")

    argv += ["-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]"]
    argv += ["-t", f"{max(0.1, duration):.3f}"]
    argv += encode_args(options, preview)
    argv += [output]
    return argv


def build_concat_command(list_file: str, output: str) -> List[str]:
    """Stitch the shots. `-c copy` is valid only because every shot shares
    encode_args() — this is a remux, not a re-encode."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-c", "copy", "-movflags", "+faststart", output,
    ]


def build_xfade_command(
    shot_files: Sequence[str], durations: Sequence[float], output: str,
    *, options: RenderOptions, preview: bool, style: str, overlap: float,
    cuts: Sequence[bool] = (),
) -> List[str]:
    """Stitch the shots with a blending transition instead of a plain concat.

    Unlike `build_concat_command` this is a real encode, because a blend needs
    adjacent shots to be on screen at the same time and no per-shot filter can
    express that. It is still only one pass over the joined stream, and it reuses
    `encode_args` so the result matches every other path's quality settings.

    Each shot is its own input and the graph chains pairwise, carrying the
    running total so every `offset` lands where the previous blend left off:
    shot k starts `overlap` seconds before the accumulated stream ends.

    The audio does not blend the way the picture does. An `acrossfade` here
    would mix the outgoing shot's trailing hold — the very silence
    `shot_end_pause_ms`/`heading_pause_ms` puts there — with the incoming
    shot's opening words ramping up underneath it, which is exactly what
    used to muffle the start of every segment after the first and swallow
    the configured pause along with it. Instead the accumulated audio is
    trimmed to end exactly where the picture starts blending, and the next
    shot's track is appended untouched: a clean cut under a blended
    picture, eating the same `overlap` seconds the video xfade does so the
    two streams stay in sync without the words ever overlapping.

    A shot whose `cuts` entry is True joins by a straight cut instead: it
    carries on over the same picture, so it is appended whole, picture and
    sound, with nothing eaten.
    """
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for name in shot_files:
        argv += ["-i", name]

    transition = XFADE_NAMES.get(style, "dissolve")
    chains: List[str] = []
    video, audio = "0:v", "0:a"
    total = durations[0]
    for index in range(1, len(shot_files)):
        if index < len(cuts) and cuts[index]:
            chains.append(f"[{video}][{index}:v]concat=n=2:v=1:a=0[vx{index}]")
            chains.append(f"[{audio}][{index}:a]concat=n=2:v=0:a=1[ax{index}]")
            video, audio = f"vx{index}", f"ax{index}"
            total += durations[index]
            continue
        offset = max(0.0, total - overlap)
        chains.append(
            f"[{video}][{index}:v]xfade=transition={transition}:"
            f"duration={overlap:.3f}:offset={offset:.3f}[vx{index}]"
        )
        chains.append(f"[{audio}]atrim=end={offset:.3f},asetpts=PTS-STARTPTS[at{index}]")
        chains.append(f"[at{index}][{index}:a]concat=n=2:v=0:a=1[ax{index}]")
        video, audio = f"vx{index}", f"ax{index}"
        total += durations[index] - overlap

    chains.append(f"[{video}]setsar=1,format=yuv420p[v]")
    argv += ["-filter_complex", ";".join(chains), "-map", "[v]", "-map", f"[{audio}]"]
    argv += encode_args(options, preview)
    argv += ["-movflags", "+faststart", output]
    return argv


def crossfade_total(durations: Sequence[float], overlap: float,
                    cuts: Sequence[bool] = ()) -> float:
    """Length of an xfade stitch: every join eats `overlap` seconds, except
    where a shot cuts straight in (see `build_xfade_command`)."""
    if not durations:
        return 0.0
    blends = sum(1 for index in range(1, len(durations))
                 if not (index < len(cuts) and cuts[index]))
    return max(0.0, sum(durations) - overlap * blends)


def build_music_command(
    source: str, music: str, output: str,
    *, duration: float, spec: MusicSpec, duck: bool,
    start: float = 0.0, end: Optional[float] = None,
) -> List[str]:
    """Mix a background bed under the finished video, without touching the picture.

    Music has to run continuously across shot boundaries, so it cannot be a
    per-shot input — it goes on after the stitch. `-c:v copy` is the point: the
    video stream is passed through untouched and only the audio is re-encoded,
    so scoring a render costs seconds rather than a second full encode.

    `-stream_loop -1` covers a bed shorter than the video and the output `-t`
    truncates one that is longer. `normalize=0` stops `amix` halving the
    narration to make room, which is the default and never what anyone wants.

    `start`/`end` narrow the bed to a window of the video — the article between
    an intro and an outro, which bring their own sound. The fades land at the
    window's edges, and the bed is padded with silence past its end so the mix
    and the ducking compressor run on to the end of the narration as before.
    """
    end = duration if end is None else max(0.0, min(end, duration))
    start = max(0.0, min(start, end))
    window = max(0.1, end - start)
    fade_out_at = max(0.0, window - max(0.0, spec.fade_out))
    bed = (f"[1:a]volume={max(0.0, min(1.0, spec.volume)):.3f},"
           f"aresample=48000,aformat=channel_layouts=stereo")
    if spec.fade_in > 0:
        bed += f",afade=t=in:st=0:d={spec.fade_in:.3f}"
    if spec.fade_out > 0:
        bed += f",afade=t=out:st={fade_out_at:.3f}:d={spec.fade_out:.3f}"
    if start > 0 or end < duration:
        bed += f",atrim=end={window:.3f}"
        if start > 0:
            delay = int(round(start * 1000))
            bed += f",adelay={delay}|{delay}"
        bed += ",apad"
    chains = [f"{bed}[m]"]

    if duck:
        # Compress the bed against the narration so it drops under speech and
        # comes back up in the gaps. The main input comes first, the key second.
        chains.append("[0:a]asplit=2[nar][key]")
        chains.append("[m][key]sidechaincompress="
                      "threshold=0.060:ratio=8:attack=15:release=350[bed]")
        chains.append("[nar][bed]amix=inputs=2:normalize=0:duration=first[a]")
    else:
        chains.append("[0:a][m]amix=inputs=2:normalize=0:duration=first[a]")

    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", source, "-stream_loop", "-1", "-i", music,
        "-filter_complex", ";".join(chains),
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{max(0.1, duration):.3f}", "-movflags", "+faststart", output,
    ]


def build_mux_command(
    source: str, output: str,
    *, chapters_file: Optional[str] = None, subtitle_file: Optional[str] = None,
) -> List[str]:
    """Attach chapter marks and/or a soft subtitle track, still without re-encoding."""
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source]
    index = 1
    chapters_index = subtitle_index = None
    if chapters_file:
        argv += ["-i", chapters_file]
        chapters_index = index
        index += 1
    if subtitle_file:
        argv += ["-i", subtitle_file]
        subtitle_index = index
        index += 1

    argv += ["-map", "0"]
    if subtitle_index is not None:
        argv += ["-map", str(subtitle_index)]
    if chapters_index is not None:
        argv += ["-map_metadata", str(chapters_index), "-map_chapters", str(chapters_index)]

    argv += ["-c", "copy"]
    if subtitle_index is not None:
        argv += ["-c:s", "mov_text"]
    argv += ["-movflags", "+faststart", output]
    return argv


def build_poster_command(source: str, output: str, at_seconds: float = 1.0) -> List[str]:
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at_seconds):.3f}", "-i", source,
        "-frames:v", "1", "-q:v", "3", output,
    ]


def build_narration_command(
    list_file: str, output: str, *, speed: float = 1.0, min_seconds: float = 0.0,
) -> List[str]:
    """Join the TTS chunks into one WAV.

    Decoding to PCM rather than concatenating MP3s avoids the frame-padding gaps
    that make joined MP3 audio click and make durations drift — and the durations
    are what every shot length and subtitle cue is derived from.
    """
    filters: List[str] = []
    # atempo only accepts 0.5-2.0, so an extreme rate is applied in stages.
    remaining = max(0.25, min(4.0, speed))
    while abs(remaining - 1.0) > 0.01:
        step = max(0.5, min(2.0, remaining))
        filters.append(f"atempo={step:.4f}")
        remaining /= step
        if len(filters) >= 4:
            break
    if min_seconds > 0:
        filters.append(f"apad=whole_dur={min_seconds:.3f}")

    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_file]
    if filters:
        argv += ["-filter:a", ",".join(filters)]
    argv += ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", output]
    return argv


def build_decode_command(source: str, output: str) -> List[str]:
    """Normalise a TTS clip to 48 kHz stereo PCM.

    The concat demuxer needs every input to share a codec and stream layout, so
    provider output (MP3 at whatever rate the model emits) is decoded before it
    is joined with the silence pads. It also makes the per-chunk durations that
    the subtitle cues are built from exact rather than frame-quantised.
    """
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", output,
    ]


def build_silence_command(output: str, seconds: float) -> List[str]:
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", f"{max(0.01, seconds):.3f}", "-c:a", "pcm_s16le", output,
    ]


def build_join_mp3_command(list_name: str, output: str) -> List[str]:
    """Join a concat playlist of WAV parts back into one MP3.

    `build_narration_command`'s counterpart for the read-aloud export path: no
    speed change and no minimum length, just the re-encode. It does not stay
    WAV because an exported or inserted clip is written into the user's media
    directory and re-fetched on every playback, and 48 kHz stereo PCM is an
    order of magnitude larger than a 128 kbps MP3 of the same narration.
    """
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", list_name,
        "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", output,
    ]


def write_concat_list(path: str, filenames: Sequence[str]) -> None:
    """Concat-demuxer playlist. Single quotes in a name are escaped per its
    (unusual) quoting rules; in practice every name here is a generated one."""
    with open(path, "w", encoding="utf-8") as f:
        for name in filenames:
            safe = name.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")


# ── GVC additions ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KenBurnsPath:
    """A camera move from one frame of a picture to another (spec S1).

    Frames are fractions of the picture: `x`, `y` the top-left, `w` the width. Their
    height follows from the output's aspect ratio, so a frame can never ask for a
    stretched picture. `picture` is the source's pixel size, needed to place the
    frames on the canvas the picture is fitted into.
    """

    start: Tuple[float, float, float]
    end: Tuple[float, float, float]
    picture: Tuple[int, int]
    ease: str = "in_out"


def path_crop_rects(
    path: KenBurnsPath, canvas_width: int, canvas_height: int, out_aspect: float,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], bool]:
    """Each frame as (x, y, width) in canvas pixels, and whether one had to move.

    The picture sits centred on the canvas at the largest size that fits (as `pad`
    and `blur` place it). A frame whose derived height would run past the picture's
    edge, or past the canvas, is moved back inside rather than refused: the spec
    cannot know the picture's shape, so this is the first place it can be checked.
    """
    pic_w, pic_h = max(1, path.picture[0]), max(1, path.picture[1])
    scale = min(canvas_width / pic_w, canvas_height / pic_h)
    shown_w, shown_h = pic_w * scale, pic_h * scale
    left, top = (canvas_width - shown_w) / 2, (canvas_height - shown_h) / 2
    moved = False
    rects = []
    for fx, fy, fw in (path.start, path.end):
        crop_w = max(2.0, min(canvas_width, fw * shown_w))
        crop_h = crop_w / out_aspect
        if crop_h > canvas_height:
            crop_h, crop_w, moved = canvas_height, canvas_height * out_aspect, True
        x, y = left + fx * shown_w, top + fy * shown_h
        cx, cy = min(max(0.0, x), canvas_width - crop_w), min(max(0.0, y), canvas_height - crop_h)
        moved = moved or abs(cx - x) > 1 or abs(cy - y) > 1
        rects.append((cx, cy, crop_w))
    return rects[0], rects[1], moved


def kenburns_path_chain(
    src: str, out: str, *, width: int, height: int, fps: int, duration: float,
    path: KenBurnsPath, preview: bool = False,
) -> str:
    """A `zoompan` move between two frames, over a picture fitted at the read size.

    The caller fits the picture onto a canvas of the output's shape at
    `kenburns_geometry`'s read size, as the preset drifts do, so a crop of the
    output's aspect is what zoompan takes (`iw/zoom` by `ih/zoom`) and nothing is
    stretched. Crop width and origin are interpolated linearly, or with a smoothstep
    for `in_out` so the move starts and ends at rest.

    Coarser than the presets' `kenburns_sweep`, which guarantees a whole read pixel
    per frame: an arbitrary path cannot, so a very slow move may step. The read
    oversampling keeps each step to a fraction of an output pixel, which is what
    makes that acceptable for M2.
    """
    read_width, read_height, write_width, write_height = kenburns_geometry(width, height, preview)
    frames = max(1, int(math.ceil(max(0.1, duration) * max(1, fps))))
    (x0, y0, w0), (x1, y1, w1), _moved = path_crop_rects(
        path, read_width, read_height, width / max(1, height))
    # zoompan's `on` runs 0..d-1 and d is frames+2 (see `kenburns_chain`), so the
    # move completes on the last frame the caller's `-t` keeps.
    span = frames + 1
    t = f"(on/{span})"
    progress = f"({t}*{t}*(3-2*{t}))" if path.ease != "linear" else t
    crop = f"({w0:.3f}+{w1 - w0:.3f}*{progress})"
    z = f"{read_width}/{crop}"
    x = f"{x0:.3f}+{x1 - x0:.3f}*{progress}"
    y = f"{y0:.3f}+{y1 - y0:.3f}*{progress}"
    chain = (f"[{src}]zoompan=z={z}:x={x}:y={y}:"
             f"d={frames + 2}:s={write_width}x{write_height}:fps={fps}")
    if (write_width, write_height) != (width, height):
        chain += f",scale={width}:{height}"
    return f"{chain}[{out}]"


def build_extract_command(
    source: str, output: str, *, start: float, length: float, with_audio: bool,
) -> List[str]:
    """Cut `length` seconds out of a video from `start`, re-encoded.

    A trimmed clip is cut out once, before its shot is built, so the shot command
    stays as Notes wrote it: looping a trim then means looping this file, which
    `-stream_loop` on the original could not do (it restarts at the file's start).
    Seeking before `-i` with a re-encode is frame-accurate. Quality is set high
    because the shot encodes it again.
    """
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, start):.3f}", "-i", source,
            "-t", f"{max(0.1, length):.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p"]
    if with_audio:
        argv += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    else:
        argv += ["-an"]
    argv += ["-avoid_negative_ts", "make_zero", output]
    return argv


def build_stitch_command(
    shot_files: Sequence[str], durations: Sequence[float], output: str,
    *, joins: Sequence[Optional[Tuple[str, float]]], options: RenderOptions, preview: bool,
    start_frame: int = 0, end_frame: Optional[int] = None, streams: str = "both",
) -> List[str]:
    """`build_xfade_command` with a transition of its own at every join.

    `joins[i]` is how shot i joins shot i-1 (`joins[0]` is unused): None appends it
    whole, which is a cut or a dip (a dip is drawn inside both shots); a pair is the
    xfade name and the overlap. Audio is handled exactly as there: trimmed to where
    the blend starts and the next shot appended, so words never overlap.

    `start_frame` drops that many frames off the front of the first shot and
    `end_frame` stops the last one at that frame: one run of a chunked stitch (see
    `plan_stitch_chunks`), whose neighbours show the rest of the shot.

    `streams` is "video" or "audio" to build only that half: the partial stitch
    (see `plan_partial_stitch`) encodes the picture only around each blend, and
    the sound for the whole video in one pass of its own.
    """
    fps = max(1, options.fps)
    durations = list(durations)
    last = len(shot_files) - 1
    if end_frame is not None:
        durations[last] = end_frame / fps
    if start_frame:
        durations[0] -= start_frame / fps
    picture, sound = streams in ("both", "video"), streams in ("both", "audio")
    # The picture alone can seek its first shot to `start_frame` rather than decode
    # its way there, which for a blend piece is most of the shot. Half a frame early,
    # so the frame-accurate seek keeps that frame however its time rounds. The sound
    # can't: a seek lands on an AAC packet, not a sample.
    seek = start_frame if streams == "video" else 0

    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for index, name in enumerate(shot_files):
        # Every input is open, with its decoder, for the whole pass. A decoder's
        # default is a thread per core and a frame buffer per thread, which made
        # this pass's memory the shot count times the core count.
        argv += ["-threads", "1"] + ([] if sound else ["-an"]) + ([] if picture else ["-vn"])
        if index == 0 and seek:
            argv += ["-ss", f"{(seek - 0.5) / fps:.6f}"]
        argv += ["-i", name]

    # Every input on one timebase first. `concat` re-times its output to
    # AV_TIME_BASE (1/1000000) while the shots carry 1/90000, and `xfade` refuses two
    # inputs that disagree — so a cut followed by a blend failed to build at all.
    vchains: List[str] = []
    achains: List[str] = []
    sounds: List[str] = []
    for i in range(len(shot_files)):
        lo = start_frame - seek if i == 0 else 0
        hi = end_frame if i == last else None
        if hi is not None and i == 0:
            hi -= seek
        if not lo and hi is None:
            vchains.append(f"[{i}:v]settb=AVTB[s{i}]")
            sounds.append(f"{i}:a")
            continue
        # Trimmed by frame and by sample rather than by seconds, so the picture and
        # the sound part at the same instant and the next run picks up exactly
        # there. 48 kHz is what `encode_args` writes every shot's audio at.
        bounds = [f"start_frame={lo}"] if lo else []
        samples = [f"start_sample={round(lo * 48000 / fps)}"] if lo else []
        if hi is not None:
            bounds.append(f"end_frame={hi}")
            samples.append(f"end_sample={round(hi * 48000 / fps)}")
        # ffmpeg 7 leaves a trimmed stream with no frame rate (1/0), and `xfade`
        # refuses one, so it is set back: the frames are already at it, so `fps`
        # neither drops nor repeats any.
        vchains.append(f"[{i}:v]trim={':'.join(bounds)},setpts=PTS-STARTPTS,"
                       f"fps={fps},settb=AVTB[s{i}]")
        achains.append(f"[{i}:a]atrim={':'.join(samples)},asetpts=PTS-STARTPTS[st{i}]")
        sounds.append(f"st{i}")
    video, audio = "s0", sounds[0]
    total = durations[0]
    for index in range(1, len(shot_files)):
        join = joins[index] if index < len(joins) else None
        if join is None:
            vchains.append(f"[{video}][s{index}]concat=n=2:v=1:a=0[vx{index}]")
            achains.append(f"[{audio}][{sounds[index]}]concat=n=2:v=0:a=1[ax{index}]")
            total += durations[index]
        else:
            name, overlap = join
            offset = max(0.0, total - overlap)
            vchains.append(
                f"[{video}][s{index}]xfade=transition={name}:"
                f"duration={overlap:.3f}:offset={offset:.3f}[vx{index}]"
            )
            achains.append(f"[{audio}]atrim=end={offset:.3f},asetpts=PTS-STARTPTS[at{index}]")
            achains.append(f"[at{index}][{sounds[index]}]concat=n=2:v=0:a=1[ax{index}]")
            total += durations[index] - overlap
        video, audio = f"vx{index}", f"ax{index}"
    vchains.append(f"[{video}]setsar=1,format=yuv420p[v]")

    shared = encode_args(options, preview)
    split = shared.index("-c:a")
    if not sound:
        argv += ["-filter_complex", ";".join(vchains), "-map", "[v]", *shared[:split], "-an"]
    elif not picture:
        # A lone input's sound needs no graph at all, and a graph with nothing in it
        # is an error, so the one-shot case maps the track straight through.
        if achains:
            argv += ["-filter_complex", ";".join(achains), "-map", f"[{audio}]"]
        else:
            argv += ["-map", f"{audio}"]
        argv += [*shared[split:], "-vn"]
    else:
        argv += ["-filter_complex", ";".join(vchains + achains),
                 "-map", "[v]", "-map", f"[{audio}]", *shared]
    argv += ["-movflags", "+faststart", output]
    return argv


# How many shots one pass of a blended stitch decodes at once. A single pass over
# every shot grew with the video, since each input holds a decoder and its frame
# buffers from the first frame to the last: about 10 MB a shot at preview size even
# single-threaded, 1.9 GB for 80 shots before that, and several times either at
# 1080p. Stitching runs of this many and remuxing the runs keeps the peak flat.
STITCH_CHUNK_SHOTS = 8


@dataclass(frozen=True)
class StitchChunk:
    """One pass of a chunked stitch: shots `first`..`last`, inclusive.

    `start_frame` is how much of `first` the previous run already showed, and
    `end_frame` where in `last` this one stops (None: the whole shot).
    """

    first: int
    last: int
    start_frame: int = 0
    end_frame: Optional[int] = None


def _join_overlap(joins: Sequence[Optional[Tuple[str, float]]], index: int) -> float:
    join = joins[index] if 0 <= index < len(joins) else None
    return join[1] if join else 0.0


def plan_stitch_chunks(
    durations: Sequence[float], joins: Sequence[Optional[Tuple[str, float]]], fps: int,
    size: int = STITCH_CHUNK_SHOTS,
) -> List[StitchChunk]:
    """Cut a blended stitch into runs whose outputs `concat -c copy` back together.

    A run can end at a cut, which needs nothing, or inside a shot, which is how a
    video blended at every join still gets split: the run stops partway through the
    shot and the next one starts there, so the blend each side stays whole inside
    one run. The split frame is the last one before the shot starts blending out,
    because the sound there is the trailing hold `shot_end_pause_ms` leaves after
    the last word: an AAC frame boundary lands in silence rather than mid-word.

    Every run is encoded with `encode_args`, so the remux is the same one the plain
    concat already relies on, and the picture is encoded once, as before.
    """
    count = len(durations)
    size = max(2, size)
    fps = max(1, fps)
    chunks: List[StitchChunk] = []
    first, start = 0, 0
    while count - first > size:
        split: Optional[Tuple[int, Optional[int]]] = None
        for j in range(first + size - 1, count - 1):
            if _join_overlap(joins, j + 1) <= 0:
                split = (j, None)
                break
            # A frame clear of both blends, with one to spare each side.
            lo = math.ceil(_join_overlap(joins, j) * fps) + 1
            hi = math.floor((durations[j] - _join_overlap(joins, j + 1)) * fps) - 1
            if lo <= hi:
                split = (j, hi)
                break
        if split is None:
            break
        j, frame = split
        chunks.append(StitchChunk(first, j, start, frame))
        first, start = (j + 1, 0) if frame is None else (j, frame)
    chunks.append(StitchChunk(first, count - 1, start, None))
    return chunks


@dataclass(frozen=True)
class StitchPiece:
    """One stretch of a partial stitch's picture, in output order.

    `blend` False: frames `start_frame`..`end_frame` of shot `first` (== `last`),
    copied as they were encoded. True: shots `first`..`last` encoded together, from
    `start_frame` of the first to `end_frame` of the last, with their blends. An
    `end_frame` of None runs to the end of the shot.
    """

    blend: bool
    first: int
    last: int
    start_frame: int = 0
    end_frame: Optional[int] = None


def probe_keyframes(path: str, fps: int) -> Tuple[List[int], int]:
    """Frame numbers of a video's keyframes, and how many frames it has.

    Read from the packets, not the frames, so nothing is decoded and a long shot
    probes in a moment.
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", path],
        capture_output=True, timeout=PROBE_TIMEOUT_SECONDS,
    )
    if out.returncode != 0:
        raise FFmpegError(f"ffprobe could not read the keyframes of {path}")
    frames = set()
    count = 0
    for line in out.stdout.decode(errors="replace").splitlines():
        when, _, flags = line.partition(",")
        count += 1
        if "K" in flags:
            try:
                frames.add(round(float(when) * fps))
            except ValueError:
                continue
    return sorted(frames), count


def plan_partial_stitch(
    durations: Sequence[float], joins: Sequence[Optional[Tuple[str, float]]],
    keyframes: Sequence[Sequence[int]], fps: int,
) -> List[StitchPiece]:
    """Lay a blended stitch out as copied stretches and the blends between them.

    A blend needs both shots decoded and encoded again, but only where they
    overlap. Every shot was encoded with `encode_args`, so between two of its
    keyframes it can be copied as it is and remuxed beside freshly encoded frames.
    Each blend is therefore re-encoded from the last keyframe of the outgoing shot
    before the blend begins to the first keyframe of the incoming one after it
    ends: a second or two a join rather than the whole video, which at 1080p on
    the `medium` preset is minutes against seconds.

    A shot with no keyframe clear of the blends at both ends (a short one, blended
    in and out) has nothing to copy, so the blend before it and the one after it
    become one encode through it.
    """
    count = len(durations)
    fps = max(1, fps)

    def overlap(index: int) -> float:
        return _join_overlap(joins, index) if 0 < index < count else 0.0

    pieces: List[StitchPiece] = []
    group: Optional[Tuple[int, int]] = None   # an open blend: (first shot, start frame)
    for i in range(count):
        frames_in, frames_out = overlap(i), overlap(i + 1)
        keys = keyframes[i] if i < len(keyframes) else [0]
        if frames_in > 0:
            after = [k for k in keys if k >= math.ceil(frames_in * fps)]
            lo: Optional[int] = after[0] if after else None
        else:
            lo = 0
        hi: Optional[int] = None
        if frames_out > 0:
            before = [k for k in keys if k <= math.floor((durations[i] - frames_out) * fps)]
            hi = before[-1] if before else 0
        body = lo is not None and (hi is None or hi > lo)
        if group is not None:
            if not body:
                if frames_out <= 0:   # the blend ends inside this shot, and so does it
                    pieces.append(StitchPiece(True, group[0], i, group[1], None))
                    group = None
                continue
            pieces.append(StitchPiece(True, group[0], i, group[1], lo))
            group = None
        start = lo or 0
        if hi is None:
            pieces.append(StitchPiece(False, i, i, start, None))
        else:
            if hi > start:
                pieces.append(StitchPiece(False, i, i, start, hi))
            group = (i, hi)
    if group is not None:
        pieces.append(StitchPiece(True, group[0], count - 1, group[1], None))
    return pieces


def build_cut_command(source: str, output_pattern: str, at_frames: Sequence[int],
                      fps: int) -> List[str]:
    """Split a shot's picture at keyframes, copied: `output_pattern` takes a %d.

    The segment muxer cuts at the first keyframe at or after each time, so each is
    asked for half a frame early: the cut lands on that keyframe however its time
    rounds. Audio is left out; the partial stitch encodes the sound separately.
    """
    times = ",".join(f"{(frame - 0.5) / max(1, fps):.6f}" for frame in at_frames)
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
        "-map", "0:v", "-c", "copy", "-an", "-f", "segment", "-segment_format", "mp4",
        # The timescale every encode writes (see `encode_args`). The segment muxer
        # would otherwise pick 1/15360, and ffmpeg 6's concat, given pieces on two
        # timebases, laid them out a minute apart.
        "-segment_format_options", "video_track_timescale=90000",
        "-segment_times", times, "-reset_timestamps", "1", output_pattern,
    ]


def build_video_copy_command(source: str, output: str) -> List[str]:
    """A shot's picture alone, copied: every file the concat joins has the same
    streams, and the partial stitch's pieces carry no sound."""
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
            "-map", "0:v", "-c", "copy", "-an", "-video_track_timescale", "90000", output]


def build_join_av_command(video_list: str, audio: str, output: str) -> List[str]:
    """Remux the partial stitch's picture pieces and its sound into one file."""
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", video_list, "-i", audio,
        "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart", output,
    ]


@dataclass(frozen=True)
class MixTrack:
    """One audio track placed on the finished video's timeline."""

    path: str
    start: float          # seconds into the video
    length: float         # how long it plays
    trim_in: float = 0.0  # seconds into the file it starts from
    loop: bool = False    # repeat the file to fill `length`
    volume: float = 0.18
    fade_in: float = 0.0
    fade_out: float = 0.0
    duck: bool = True     # pushed down under the narration
    during_clips: Optional[str] = None   # None, "mute" or "play": see AudioTrack


# How long the score takes to leave before a clip and come back after it.
CLIP_FADE_SECONDS = 0.6


def _quiet_during(windows: Sequence[Tuple[float, float]], fade: float) -> str:
    """A `volume` expression that is 1, except 0 inside each window, ramping over
    `fade` seconds either side of it so the sound leaves and returns rather than
    cutting. Quoted, since an expression's commas would otherwise split the graph."""
    fade = max(0.01, fade)
    terms = [f"(1-max(0,min(1,min((t-{start - fade:.3f})/{fade:.3f},"
             f"({end + fade:.3f}-t)/{fade:.3f}))))" for start, end in windows]
    return "'" + "*".join(terms) + "'"


def build_mix_command(
    source: str, tracks: Sequence[MixTrack], output: str,
    *, duration: float, duck_available: bool = True,
    clip_windows: Sequence[Tuple[float, float]] = (),
) -> List[str]:
    """Mix any number of tracks under the finished video, the picture untouched.

    `build_music_command` for N tracks, each anywhere on the timeline: a soundtrack
    that changes partway through is two tracks, and a crossfade is two that overlap
    with matching fades. Each is trimmed to its window, faded, set to its volume and
    delayed to its start. The ducked ones (music, by default) are summed into one bed
    and compressed against the narration, as Notes ducks its single bed; the rest
    (sound effects, extra voice) are mixed in flat.

    A looping track restarts from the top of its file, not from `trim_in`: that is
    what `-stream_loop` does with an input seek, and a bed short enough to loop is
    rarely trimmed as well.

    `clip_windows` are where a clip plays its own sound. A track set to "mute"
    there fades out around each one. The narration's key carries the clips too,
    which is what dips a ducked bed under them; a ducked track set to "play" is
    compressed against a key with the clips taken out, so only the voice moves it.
    """
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source]
    chains: List[str] = []
    ducked: List[str] = []
    spared: List[str] = []
    flat: List[str] = []
    for position, track in enumerate(tracks, start=1):
        if track.trim_in > 0:
            argv += ["-ss", f"{track.trim_in:.3f}"]
        if track.loop:
            argv += ["-stream_loop", "-1"]
        argv += ["-i", track.path]
        length = max(0.1, track.length)
        chain = (f"[{position}:a]aresample=48000,aformat=channel_layouts=stereo,"
                 f"atrim=end={length:.3f},asetpts=PTS-STARTPTS,"
                 f"volume={max(0.0, min(1.0, track.volume)):.3f}")
        if track.fade_in > 0:
            chain += f",afade=t=in:st=0:d={min(track.fade_in, length):.3f}"
        if track.fade_out > 0:
            fade = min(track.fade_out, length)
            chain += f",afade=t=out:st={length - fade:.3f}:d={fade:.3f}"
        delay = int(round(max(0.0, track.start) * 1000))
        if delay:
            chain += f",adelay={delay}|{delay}"
        chain += ",apad"
        if track.during_clips == "mute" and clip_windows:
            # After the delay, so `t` is the video's own clock.
            chain += f",volume={_quiet_during(clip_windows, CLIP_FADE_SECONDS)}:eval=frame"
        chains.append(chain + f"[t{position}]")
        if not (track.duck and duck_available):
            flat.append(f"t{position}")
        elif track.during_clips == "play" and clip_windows:
            spared.append(f"t{position}")
        else:
            ducked.append(f"t{position}")

    mix_inputs = ["nar"]
    beds = [(name, group) for name, group in (("bed", ducked), ("spared", spared)) if group]
    if beds:
        keys = (["key"] if ducked else []) + (["keyvoice"] if spared else [])
        chains.append(f"[0:a]asplit={1 + len(keys)}[nar]" + "".join(f"[{k}]" for k in keys))
        if spared:
            # The clips cut out of the key, quickly, so the bed is not ducked
            # across them; the voice either side still is.
            chains.append(f"[keyvoice]volume={_quiet_during(clip_windows, 0.05)}:eval=frame"
                          "[keyspared]")
        for name, group in beds:
            if len(group) == 1:
                source_label = group[0]
            else:
                chains.append("".join(f"[{t}]" for t in group)
                              + f"amix=inputs={len(group)}:normalize=0[{name}mix]")
                source_label = f"{name}mix"
            key = "key" if name == "bed" else "keyspared"
            chains.append(f"[{source_label}][{key}]sidechaincompress="
                          f"threshold=0.060:ratio=8:attack=15:release=350[{name}]")
            mix_inputs.append(name)
    else:
        chains.append("[0:a]anull[nar]")
    mix_inputs += flat
    chains.append("".join(f"[{t}]" for t in mix_inputs)
                  + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=first[a]")

    argv += [
        "-filter_complex", ";".join(chains),
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-t", f"{max(0.1, duration):.3f}", "-movflags", "+faststart", output,
    ]
    return argv


@dataclass(frozen=True)
class TimedLayer:
    """A full-frame RGBA PNG shown over the finished video for a window."""

    path: str
    start: float
    end: float
    fade: float = 0.0


@dataclass(frozen=True)
class TimedWave:
    """An audio wave drawn over the finished video for a window (a scene's `waveform`).

    `spec` carries the same fields as the project-wide waveform (mode, colour, opacity,
    position, height_pct, scrim), so one drawing routine serves both.
    """

    spec: object
    start: float
    end: float
    fade: float = 0.0


def wave_layer_chain(audio_src: str, stage: str, out: str, wave: TimedWave, *,
                     width: int, height: int, fps: int, total: float) -> str:
    """One windowed wave: the video's own audio for the window, drawn, faded, placed.

    The band (scrim box and wave together) is built as its own stream and then faded as
    one, so the scrim fades with the wave instead of popping on. Its timestamps are
    moved to the window's start the same way a PNG layer's are (see
    `build_overlay_pass`), so `eof_action=pass` hands the picture back afterwards.
    """
    spec = wave.spec
    start = max(0.0, min(wave.start, total))
    end = max(start, min(wave.end, total))
    seconds = max(0.1, end - start)
    band, y = wave_band(height, spec)
    alpha = max(0.05, min(1.0, spec.opacity))
    scrim = max(0.0, min(1.0, spec.scrim))
    parts = [
        f"[{audio_src}]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
        f"aformat=channel_layouts=mono,"
        f"showwaves=s={width}x{band}:mode={spec.mode}:draw=full:scale=sqrt:"
        f"rate={fps}:colors={_hex_to_ffmpeg(spec.color)},format=rgba,"
        f"colorchannelmixer=aa={alpha}[{out}_w]"
    ]
    band_stream = f"{out}_w"
    if scrim > 0.01:
        parts.append(f"color=c=black@{scrim}:s={width}x{band}:r={fps}:d={seconds:.3f},"
                     f"format=rgba[{out}_box]")
        parts.append(f"[{out}_box][{out}_w]overlay=format=auto:shortest=1[{out}_b]")
        band_stream = f"{out}_b"
    placed = f"[{band_stream}]setpts=PTS-STARTPTS+{start:.3f}/TB"
    if wave.fade > 0:
        placed += (f",fade=t=in:st={start:.3f}:d={wave.fade:.3f}:alpha=1"
                   f",fade=t=out:st={end - wave.fade:.3f}:d={wave.fade:.3f}:alpha=1")
    parts.append(placed + f"[{out}_p]")
    parts.append(f"[{stage}][{out}_p]overlay=0:{y}:eof_action=pass:"
                 f"enable='between(t,{start:.3f},{end:.3f})'[{out}]")
    return ";".join(parts)


def build_overlay_pass(
    source: str, layers: Sequence[TimedLayer], output: str,
    *, options: RenderOptions, preview: bool, duration: float,
    waves: Sequence[TimedWave] = (), width: int = 0, height: int = 0,
) -> List[str]:
    """Draw timed layers over the stitched picture, the sound untouched.

    Per shot would have kept the shot cache, but an overlay may run across a join (a
    title held through a dissolve), and a shot can't draw what lies past its end.
    So this is one re-encode of the whole picture after the stitch, done only when a
    video has timed overlays at all.

    Each layer is its PNG read once, as a single frame, and repeated inside the
    graph for its window only: `loop` repeats it, `trim` stops it after the
    window's frames and `setpts` places them from the layer's start. Its fades are
    then alpha fades at absolute times on the video's own clock, `enable` keeps it
    off outside its window, and `eof_action=pass` lets the picture through after.

    Two ways of doing this have failed. Looping each PNG as an input for the whole
    video decoded it on every frame, which made this pass's memory and time grow
    with the overlay count: thirty layers took 560 MB and twenty times as long. An
    input per layer that starts late (`-itsoffset`) deadlocked Debian's ffmpeg
    7.1.5 at the first layer's start: idle, never finishing, until the timeout. A
    one-frame input is finished before the picture starts, and from then on the
    overlay only pulls the layer's frames through the graph as it needs them, so
    nothing is left waiting on ffmpeg's scheduling of inputs.
    """
    fps = max(1, options.fps)
    total = max(0.1, duration)
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source]
    chains: List[str] = []
    stage = "0:v"
    # Waves go under the text and pictures, as Notes draws its waveform under its text.
    # Each reads the video's own sound, and a pad can be read once, hence the split.
    if waves:
        if len(waves) == 1:
            chains.append("[0:a]anull[wa1]")
        else:
            outs = "".join(f"[wa{n}]" for n in range(1, len(waves) + 1))
            chains.append(f"[0:a]asplit={len(waves)}{outs}")
        for n, wave in enumerate(waves, start=1):
            chains.append(wave_layer_chain(f"wa{n}", stage, f"wv{n}", wave, width=width,
                                           height=height, fps=fps, total=total))
            stage = f"wv{n}"
    for position, layer in enumerate(layers, start=1):
        start = max(0.0, min(layer.start, total))
        # Every frame that starts inside the window, the last one included.
        frames = max(1, math.ceil((min(layer.end, total) - start) * fps - 1e-6))
        argv += ["-i", layer.path]
        # `settb` first: a lone PNG comes in on the image demuxer's 1/25 timebase,
        # which would round every frame's time, and with it the fades, to 40 ms.
        chain = (f"[{position}:v]format=rgba,loop=loop=-1:size=1,trim=end_frame={frames},settb=AVTB,"
                 f"setpts=N/({fps}*TB)+{start:.3f}/TB")
        if layer.fade > 0:
            chain += (f",fade=t=in:st={layer.start:.3f}:d={layer.fade:.3f}:alpha=1"
                      f",fade=t=out:st={layer.end - layer.fade:.3f}:d={layer.fade:.3f}:alpha=1")
        chains.append(chain + f"[l{position}]")
        chains.append(f"[{stage}][l{position}]overlay=0:0:eof_action=pass:"
                      f"enable='between(t,{layer.start:.3f},{layer.end:.3f})'[v{position}]")
        stage = f"v{position}"
    # Only the video codec flags: the sound is copied, not re-encoded a second time.
    shared = encode_args(options, preview)
    video_args = shared[:shared.index("-c:a")]
    argv += [
        "-filter_complex", ";".join(chains),
        "-map", f"[{stage}]", "-map", "0:a?",
        *video_args, "-c:a", "copy",
        "-t", f"{total:.3f}", "-movflags", "+faststart", output,
    ]
    return argv
