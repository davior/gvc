"""A VideoSpec in, an MP4 out.

Notes' pipeline (`gecko-notes/backend/app/video/renderer.py`), re-driven by GVC's own
compiled timeline instead of Notes' shot list:

    fetch media -> plan units -> narrate each beat -> encode each unit
        -> stitch (per-join transitions) -> mix the soundtrack -> chapters, subtitles

Every unit is encoded to its own MP4 with identical codec settings, so a stitch with
no blends is a `concat -c copy` remux, and a unit is the unit of progress and of the
shot cache. Everything happens in a scratch directory removed on every exit; only the
finished files are moved out.

Narration is synthesised **per beat** rather than per unit, and the beats' WAVs then
joined. That costs nothing extra in TTS (the same chunks are read either way) and is
what tells us exactly when each beat starts, which anchors pointing at a beat (a sound
effect on a line) need.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from app.render import compose, shot_cache
from app.render import ffmpeg as F
from app.render.compile import (
    OverlayPlacement, Unit, beat_pause_ms, chapters, credits_units, layout, place_overlays,
    place_tracks, placement, plan_units, unit_duration, xfade_name,
)
from app.render.credits import credit_lines, description_text
from app.render.media import MediaCache, resolve
from app.render.narration import Cue, build_silence, shift_cues, synthesize_shot, write_srt
from app.render.options import (
    BackgroundSpec, CardTextSpec, CodeSpec, KenBurnsSpec, OverlayTextSpec, QuoteSpec,
    RenderOptions, TransitionSpec, WatermarkSpec, WaveformSpec, frame_size, kenburns_geometry,
)
from app.render.tts import NotesSpeech
from app.gam.client import GamClient
from app.spec.model import VideoSpec

logger = logging.getLogger(__name__)

Progress = Callable[[str, int, str], None]

NARRATION_SHARE = 40
RENDER_SHARE = 45


class RenderRefused(Exception):
    """The spec cannot be rendered as it stands; the message says what to fix."""


@dataclass
class RenderOutput:
    video: str
    subtitles: Optional[str]
    poster: Optional[str]
    duration: float
    size_bytes: int
    narration_chars: int
    warnings: List[str] = field(default_factory=list)
    # Text to paste where the video is published: chapters and credits. None: nothing
    # to say.
    description: Optional[str] = None


def base_options(spec: VideoSpec) -> RenderOptions:
    """The spec's project-wide settings as the per-shot options the builders take.

    `RenderOptions` is Notes' type and stays internal: a unit gets its own copy with
    its fit, motion and joins, so nothing here is the source of truth for anything.
    """
    style, chrome, voice = spec.style, spec.chrome, spec.voice
    watermark = chrome.watermark
    overlay = chrome.overlay_text
    wave = chrome.waveform
    return RenderOptions(
        aspect=spec.output.aspect, resolution=spec.output.resolution,
        quality=spec.output.quality, fps=spec.output.fps, fit=style.fit,
        fallback=BackgroundSpec(type=style.background.type if style.background.type != "image"
                                else "gradient",
                                colors=style.background.colors, angle=style.background.angle),
        waveform=(WaveformSpec(enabled=True, mode=wave.mode, color=wave.color, opacity=wave.opacity,
                               position=wave.position, height_pct=wave.height_pct, scrim=wave.scrim)
                  if wave else WaveformSpec()),
        watermark=(WatermarkSpec(enabled=True, text=watermark.text, position=watermark.position,
                                 opacity=watermark.opacity, scale_pct=watermark.scale_pct,
                                 caption_pct=watermark.caption_pct, margin_pct=watermark.margin_pct)
                   if watermark else WatermarkSpec()),
        overlay_text=(OverlayTextSpec(enabled=True, mode=overlay.mode,
                                      text=overlay.text if overlay.mode == "fixed" else spec.title,
                                      position=overlay.position, color=overlay.color,
                                      size_pct=overlay.size_pct, margin_pct=overlay.margin_pct,
                                      shadow=overlay.shadow)
                      if overlay else OverlayTextSpec()),
        title_card_text=CardTextSpec(**style.cards.title.model_dump()),
        chapter_card_text=CardTextSpec(**style.cards.chapter.model_dump()),
        transition=TransitionSpec(style=style.transition.style, duration=style.transition.duration),
        ken_burns=KenBurnsSpec(effect="none", amount=style.motion.amount,
                               include_cards=style.cards.motion),
        quotes=QuoteSpec(enabled=True, **style.quote.model_dump()),
        code=CodeSpec(**style.code.model_dump()),
        subtitles=spec.output.subtitles, embed_chapters=spec.output.chapters,
        thumbnail=spec.output.thumbnail, speed=voice.speed,
        paragraph_pause_ms=voice.pauses.paragraph_ms, heading_pause_ms=voice.pauses.heading_ms,
        shot_end_pause_ms=voice.pauses.segment_end_ms,
        min_shot_seconds=style.min_segment_seconds, card_seconds=style.cards.seconds,
    )


def _chapters_file(path: str, marks) -> bool:
    usable = [(s, e, t) for s, e, t in marks if t.strip() and e > s + 0.5]
    if not usable:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(";FFMETADATA1\n")
        for start, end, title in usable:
            safe = (title.replace("\\", "\\\\").replace("=", "\\=")
                         .replace(";", "\\;").replace("#", "\\#").replace("\n", " "))
            f.write("[CHAPTER]\nTIMEBASE=1/1000\n")
            f.write(f"START={int(start * 1000)}\nEND={int(end * 1000)}\ntitle={safe}\n")
    return True


@dataclass
class _Narrated:
    path: Optional[str]
    duration: float
    cues: List[Cue]
    beats: Dict[str, Tuple[float, float]]


def _narrate(spec: VideoSpec, unit: Unit, index: int, work_dir: str, options: RenderOptions,
             speech: NotesSpeech) -> _Narrated:
    """Read a unit's beats, one after another, and join them into one WAV."""
    parts: List[str] = []
    cues: List[Cue] = []
    spans: Dict[str, Tuple[float, float]] = {}
    cursor = 0.0
    for position, beat in enumerate(unit.beats):
        pause = beat_pause_ms(spec, unit.beats, position)
        if beat.speak and beat.text.strip():
            beat_options = options.model_copy(update={
                "speed": unit.speed, "shot_end_pause_ms": pause,
                # Beats are joined below; only the unit as a whole has a minimum.
                "min_shot_seconds": 0.5,
            })
            result = synthesize_shot(beat.text, index=index * 1000 + position, work_dir=work_dir,
                                     options=beat_options, tts=speech.caller(unit.voice))
            if result.path:
                parts.append(result.path)
            cues.extend(shift_cues(result.cues, cursor))
            length = result.duration
        else:
            # A silent beat holds the picture for its `hold`, then its pause.
            length = (beat.hold or 0.0) + pause / 1000.0
            pad = build_silence(work_dir, int(length * 1000)) if length > 0 else None
            if pad:
                parts.append(pad)
            else:
                length = 0.0
        spans[beat.id] = (cursor, cursor + length)
        cursor += length

    if not parts:
        return _Narrated(path=None, duration=0.0, cues=[], beats=spans)
    list_name = f"unit_{index:04d}.txt"
    out = f"unit_{index:04d}.wav"
    F.write_concat_list(os.path.join(work_dir, list_name), parts)
    F.run(F.build_narration_command(list_name, out), cwd=work_dir, timeout=600)
    duration = F.probe_duration(os.path.join(work_dir, out)) or cursor
    return _Narrated(path=out, duration=duration, cues=cues, beats=spans)


def _background(unit: Unit, spec: VideoSpec, options: RenderOptions, work_dir: str, index: int,
                width: int, height: int, background_image: Optional[str]) -> str:
    """The still a card, or a scene without a picture, sits on."""
    base = None
    if background_image:
        base = compose.cover_image(background_image, width, height)
    if base is None:
        fallback = options.fallback
        base = (compose.solid_background(width, height, fallback.colors[0])
                if fallback.type == "solid"
                else compose.gradient_background(width, height, fallback.colors, fallback.angle))
    if unit.kind == "card" and unit.credits:
        image = compose.credits_card(width, height, lines=unit.credits, background=base)
    elif unit.kind == "card" and unit.card:
        image = compose.card_image(
            width, height, title=unit.card.title or spec.title or "Untitled",
            subtitle=unit.card.subtitle or "", background=base,
            sizes=(options.chapter_card_text if unit.card.variant == "chapter"
                   else options.title_card_text),
        )
    else:
        image = base
    name = f"bg_{index:04d}.png"
    image.convert("RGB").save(os.path.join(work_dir, name), "PNG")
    return name


def _stitch_blended(
    shot_files: List[str], durations: List[float], joins: list, output: str,
    *, options: RenderOptions, preview: bool, work_dir: str,
) -> None:
    """Blend the shots together a few at a time, then remux the runs into `output`."""
    chunks = F.plan_stitch_chunks(durations, joins, options.fps)
    names: List[str] = []
    for number, chunk in enumerate(chunks):
        name = output if len(chunks) == 1 else f"stitch_{number:03d}.mp4"
        span = slice(chunk.first, chunk.last + 1)
        F.run(F.build_stitch_command(shot_files[span], durations[span], name,
                                     joins=[None] + list(joins[chunk.first + 1:chunk.last + 1]),
                                     options=options, preview=preview,
                                     start_frame=chunk.start_frame, end_frame=chunk.end_frame),
              cwd=work_dir, timeout=F.shot_timeout(sum(durations[span])))
        names.append(name)
    if len(names) > 1:
        F.write_concat_list(os.path.join(work_dir, "stitch.txt"), names)
        F.run(F.build_concat_command("stitch.txt", output), cwd=work_dir, timeout=1800)


def render(
    *, spec: VideoSpec, preview: bool, work_dir: str, out_dir: str, data_dir: str, user_id: str,
    gam: GamClient, speech: NotesSpeech, progress: Progress,
    max_segments: int, max_narration_chars: int,
) -> RenderOutput:
    if not F.ffmpeg_available():
        raise RuntimeError("ffmpeg and ffprobe must be installed on the server")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    warnings: List[str] = []
    width, height = frame_size(spec.output.aspect, spec.output.resolution, preview)

    progress("Preparing", 1, "Fetching pictures, footage and music")
    resolved = resolve(spec, gam, cache=MediaCache(Path(data_dir) / "cache" / "media"),
                       work_dir=work_dir, preview=preview, frame=(width, height))
    if resolved.problems:
        raise RenderRefused(" ".join(resolved.problems))
    media = resolved.media

    units = plan_units(spec, media, warnings)
    if not units:
        raise RenderRefused("This video has nothing in it to render yet.")
    lines = credit_lines(spec, resolved.credits)
    units += credits_units(spec, lines)
    if len(units) > max_segments:
        raise RenderRefused(f"This video has {len(units)} shots, above the limit of {max_segments}.")
    chars = sum(len(b.text) for u in units for b in u.beats if b.speak)
    if chars > max_narration_chars:
        raise RenderRefused(f"This video has {chars:,} characters of narration, above the limit "
                            f"of {max_narration_chars:,}.")
    if spec.voice.expressivity is not None:
        warnings.append("Voice expressivity is not passed to the narrator yet.")

    options = base_options(spec)
    background_image = (media[spec.style.background.asset].path
                        if spec.style.background.type == "image" and spec.style.background.asset
                        in media else None)
    watermark_icon = (media[spec.chrome.watermark.asset].path
                      if spec.chrome.watermark and spec.chrome.watermark.asset in media else None)

    # ── narrate ──────────────────────────────────────────────────────────────
    narrated: List[_Narrated] = []
    speaking = sum(1 for u in units if u.beats)
    done = 0
    for index, unit in enumerate(units):
        if unit.beats:
            done += 1
            progress("Narrating", 2 + NARRATION_SHARE * done // max(1, speaking),
                     f"shot {done} of {speaking}")
        narrated.append(_narrate(spec, unit, index, work_dir, options, speech))

    durations = [unit_duration(u, n.duration, spec.style.cards.seconds)
                 for u, n in zip(units, narrated)]
    timeline = layout(units, durations, warnings)

    # ── encode each unit ─────────────────────────────────────────────────────
    cache = shot_cache.ShotCache(data_dir, user_id)
    try:
        shot_cache.prune(data_dir)
    except Exception:
        logger.exception("Could not prune the shot cache")
    base = 2 + NARRATION_SHARE
    shot_files: List[str] = []
    current_chapter: Optional[str] = None
    for index, (unit, narration) in enumerate(zip(units, narrated)):
        progress("Rendering", base + RENDER_SHARE * index // len(units),
                 f"shot {index + 1} of {len(units)}")
        duration = timeline.durations[index]
        unit_options = options.model_copy(deep=True)
        unit_options.fit = unit.fit
        if not unit.chrome:
            unit_options.waveform.enabled = False

        path = None
        if unit.motion is not None and unit.kind in ("still", "card"):
            if unit.motion.effect == "path":
                media_item = unit.media
                if media_item and media_item.width and media_item.height:
                    path = F.KenBurnsPath(
                        start=(unit.motion.from_.x, unit.motion.from_.y, unit.motion.from_.w),
                        end=(unit.motion.to.x, unit.motion.to.y, unit.motion.to.w),
                        picture=(media_item.width, media_item.height),
                        ease=unit.motion.ease or "in_out",
                    )
                    if F.path_crop_rects(path, *kenburns_geometry(width, height, preview)[:2],
                                         width / height)[2]:
                        warnings.append(f"Shot {index + 1}: a Ken Burns frame ran off the "
                                        "picture and was moved back inside it")
            else:
                unit_options.ken_burns.effect = unit.motion.effect
                unit_options.ken_burns.amount = unit.motion.amount

        has_audio = False
        if unit.kind in ("card",) or (unit.kind == "still" and unit.media is None):
            drift = F.kenburns_effect_for(unit.kind, index, unit_options)
            draw_w, draw_h = (kenburns_geometry(width, height, preview)[:2] if drift
                              else (width, height))
            background = _background(unit, spec, unit_options, work_dir, index, draw_w, draw_h,
                                     background_image)
        elif unit.kind == "still":
            background = unit.media.path
        else:
            background = unit.media.path
            has_audio = unit.media.has_audio
            if unit.trim is not None:
                start, length = unit.trim
                if length is None:
                    length = max(0.1, (unit.media.duration or 0.0) - start)
                # Past the file's end `-t` yields less, and the shot holds its last frame.
                length += unit.tail
                clip = f"clip_{index:04d}.mp4"
                F.run(F.build_extract_command(background, clip, start=start, length=length,
                                              with_audio=unit.kind == "video_sound"),
                      cwd=work_dir, timeout=F.shot_timeout(length))
                background = clip

        # Watermark, overlay text and a quote or code panel, as one layer.
        if unit.chapter:
            current_chapter = unit.chapter
        layer = None
        if unit.chrome:
            chapter_line = (current_chapter if options.overlay_text.mode == "title_chapter"
                            and current_chapter and current_chapter != spec.title else None)
            watermark = unit_options.watermark.model_copy()
            if watermark.enabled and not watermark.text.strip() and spec.title:
                watermark.text = f"by {spec.title}"
            layer = compose.overlay_layer(width, height, watermark=watermark,
                                          watermark_icon=watermark_icon,
                                          overlay_text=unit_options.overlay_text,
                                          chapter_line=chapter_line)
        if unit.panel is not None:
            panel = (compose.quote_panel(width, height, text=unit.panel.text,
                                         attribution=unit.panel.attribution, spec=options.quotes)
                     if unit.panel.kind == "quote"
                     else compose.code_panel(width, height, text=unit.panel.text, spec=options.code))
            if panel is not None:
                if layer is not None:
                    panel.alpha_composite(layer)
                layer = panel
        overlay_png = None
        if layer is not None:
            overlay_png = f"overlay_{index:04d}.png"
            layer.save(os.path.join(work_dir, overlay_png), "PNG")

        shot_srt = None
        if spec.output.subtitles == "burn" and narration.cues:
            name = f"shot_{index:04d}.srt"
            if write_srt(os.path.join(work_dir, name), narration.cues):
                shot_srt = name

        join_in = timeline.joins[index]
        join_out = timeline.joins[index + 1] if index + 1 < len(units) else None
        in_transition = (TransitionSpec(style=join_in.style, duration=join_in.duration)
                         if join_in else TransitionSpec(style="none"))
        out_transition = (TransitionSpec(style=join_out.style, duration=join_out.duration)
                          if join_out else TransitionSpec(style="none"))
        output = f"shot_{index:04d}.mp4"

        def argv(with_options: RenderOptions, with_path=path) -> List[str]:
            return F.build_shot_command(
                kind=unit.kind if unit.kind != "card" else "card", background=background,
                audio=narration.path if unit.kind != "video_sound" else None,
                duration=duration, output=output, options=with_options, preview=preview,
                overlay_png=overlay_png, subtitle_file=shot_srt, background_has_audio=has_audio,
                index=index, in_transition=in_transition, out_transition=out_transition,
                loop=unit.loop, path=with_path,
            )

        if narration.path is None and unit.kind != "video_sound":
            # Every shot needs an audio track for the stitch: silence, then.
            silence = build_silence(work_dir, int(duration * 1000))
            narration.path = silence

        key = shot_cache.shot_key(argv(unit_options), [background, narration.path, overlay_png,
                                                        shot_srt], work_dir)
        fell_back = cache.restore(key, os.path.join(work_dir, output))
        if fell_back is None:
            try:
                F.run(argv(unit_options), cwd=work_dir, timeout=F.shot_timeout(duration))
                fell_back = False
            except F.FFmpegError as exc:
                logger.warning("Shot %d failed (%s); retrying it plainer", index + 1, exc)
                plain = unit_options.model_copy(deep=True)
                plain.ken_burns.effect = "none"
                plain.waveform.enabled = False
                F.run(argv(plain, None), cwd=work_dir, timeout=F.shot_timeout(duration))
                fell_back = True
            cache.store(key, os.path.join(work_dir, output), plain=fell_back)
        if fell_back:
            warnings.append(f"Shot {index + 1} was rendered without motion or a waveform.")
        shot_files.append(output)

    # ── stitch ───────────────────────────────────────────────────────────────
    progress("Stitching", base + RENDER_SHARE, f"joining {len(shot_files)} shots")
    blends = [(xfade_name(j.style), j.overlap) if j and j.is_blend else None
              for j in timeline.joins]
    stitched = "stitched.mp4"
    if any(blends):
        try:
            _stitch_blended(shot_files, timeline.durations, blends, stitched,
                            options=options, preview=preview, work_dir=work_dir)
        except F.FFmpegError as exc:
            # The blends cost a re-encode; if that fails, the shots still join by cuts,
            # and the timeline is re-laid without their overlaps to match. A clip's
            # tail stays, as a moment more of it before the cut.
            logger.warning("Blended stitch failed (%s); joining with cuts", exc)
            warnings.append("Blends were joined as cuts: blending the shots together failed.")
            for join in timeline.joins:
                if join and join.is_blend:
                    join.overlap = 0.0
            timeline = layout_without_overlaps(timeline)
            blends = []
    if not any(blends):
        F.write_concat_list(os.path.join(work_dir, "shots.txt"), shot_files)
        F.run(F.build_concat_command("shots.txt", stitched), cwd=work_dir, timeout=1800)
    final = stitched
    where = placement(units, timeline, [n.beats for n in narrated])

    # ── timed overlays ───────────────────────────────────────────────────────
    timed = place_overlays(spec, media, where, warnings)
    layers = _overlay_layers(timed, work_dir, width, height)
    if layers:
        progress("Drawing overlays", 88,
                 f"{len(layers)} overlay{'s' if len(layers) != 1 else ''}")
        F.run(F.build_overlay_pass(final, layers, "overlaid.mp4", options=options,
                                   preview=preview, duration=timeline.total),
              cwd=work_dir, timeout=F.shot_timeout(timeline.total))
        final = "overlaid.mp4"

    # ── the soundtrack ───────────────────────────────────────────────────────
    tracks = place_tracks(spec, media, where, warnings)
    if tracks:
        progress("Mixing", 90, f"{len(tracks)} audio track{'s' if len(tracks) != 1 else ''}")
        mix = [F.MixTrack(path=t.media.path, start=t.start, length=t.length, trim_in=t.trim_in,
                          loop=t.loop, volume=t.track.volume, fade_in=t.track.fade_in,
                          fade_out=t.track.fade_out, duck=t.duck) for t in tracks]
        F.run(F.build_mix_command(final, mix, "scored.mp4", duration=timeline.total,
                                  duck_available="sidechaincompress" in F.available_filters()),
              cwd=work_dir, timeout=1800)
        final = "scored.mp4"

    # ── chapters and subtitles ───────────────────────────────────────────────
    all_cues: List[Cue] = []
    for index, narration in enumerate(narrated):
        all_cues.extend(shift_cues(narration.cues, timeline.starts[index]))
    srt_written = write_srt(os.path.join(work_dir, "subtitles.srt"), all_cues)
    chapters_name = ("chapters.ffmeta"
                     if spec.output.chapters and _chapters_file(
                         os.path.join(work_dir, "chapters.ffmeta"), chapters(units, timeline))
                     else None)
    subtitle_name = "subtitles.srt" if srt_written and spec.output.subtitles == "soft" else None
    if chapters_name or subtitle_name:
        progress("Finishing", 94, "adding chapters and subtitles")
        F.run(F.build_mux_command(final, "final.mp4", chapters_file=chapters_name,
                                  subtitle_file=subtitle_name), cwd=work_dir, timeout=900)
        final = "final.mp4"

    progress("Finishing", 96, "saving")
    video = os.path.join(out_dir, "video.mp4")
    shutil.move(os.path.join(work_dir, final), video)
    cache.discard_used()
    subtitles = None
    if srt_written and spec.output.subtitles != "off":
        subtitles = os.path.join(out_dir, "subtitles.srt")
        shutil.move(os.path.join(work_dir, "subtitles.srt"), subtitles)
    poster = None
    if spec.output.thumbnail:
        poster = os.path.join(out_dir, "poster.jpg")
        try:
            F.run(F.build_poster_command(video, poster,
                                         at_seconds=min(1.0, max(0.0, timeline.total / 2))),
                  timeout=120)
        except (F.FFmpegError, OSError) as exc:
            logger.warning("Poster frame failed: %s", exc)
            poster = None

    return RenderOutput(
        video=video, subtitles=subtitles, poster=poster,
        duration=F.probe_duration(video) or timeline.total,
        size_bytes=os.path.getsize(video), narration_chars=speech.characters, warnings=warnings,
        description=description_text(spec, lines, chapters(units, timeline)) or None,
    )


def _overlay_layers(timed: List[OverlayPlacement], work_dir: str, width: int,
                    height: int) -> List[F.TimedLayer]:
    """Each placed overlay drawn to its own PNG."""
    layers: List[F.TimedLayer] = []
    for position, item in enumerate(timed):
        overlay = item.overlay
        if overlay.type == "text":
            image = compose.text_layer(width, height, text=overlay.text,
                                       position=overlay.position, size_pct=overlay.size_pct,
                                       color=overlay.color)
        elif overlay.type == "lower_third":
            image = compose.lower_third_layer(width, height, title=overlay.title,
                                              subtitle=overlay.subtitle or "")
        else:
            image = compose.image_layer(width, height, picture=item.media.path,
                                        position=overlay.position, scale_pct=overlay.scale_pct,
                                        opacity=overlay.opacity)
        if image is None:
            continue
        name = f"timed_{position:03d}.png"
        image.save(os.path.join(work_dir, name), "PNG")
        layers.append(F.TimedLayer(path=name, start=item.start, end=item.end, fade=item.fade))
    return layers


def layout_without_overlaps(timeline):
    """The same units laid end to end, for when blends had to become cuts."""
    starts, cursor = [], 0.0
    for duration in timeline.durations:
        starts.append(cursor)
        cursor += duration
    timeline.starts, timeline.total = starts, cursor
    return timeline
