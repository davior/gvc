"""VideoSpec -> units -> a laid-out timeline. Pure: no ffmpeg, no network, no disk.

This is the compile step of the Notes spec doc §5.8, done natively rather than by
mapping the spec back onto Notes' flat shot list (plan of attack, D1). Notes' mapping
is why it refuses per-scene transitions, per-scene motion and more than one track:
its target could not say them. Here each of those is a field on a unit or a join.

Three stages, each testable alone:

1. `plan_units`: segments become units. A scene is cut at each beat that carries a
   quote or code overlay (each such beat is a unit of its own, drawn as a screen
   with its panel, as Notes always has); a card or a clip is one unit. Defaults
   cascade project -> segment here, once.
2. `unit_duration`: once narration has been synthesised and measured (the renderer
   does that), how long each unit runs.
3. `layout`: units end to end, with each join's transition, and the overlap a blend
   takes. Then `resolve_anchor` turns the spec's structural anchors ("the start of
   the market scene, 3 s early") into seconds on that timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

from app.render.ffmpeg import KENBURNS_CYCLE, MIN_TRANSITION_SECONDS, XFADE_MAX_SHOTS
from app.render.options import XFADE_NAMES, is_crossfade
from app.spec.model import (
    AnchorRef, AudioTrack, Beat, Card, CodeOverlay, ImageOverlay, LowerThirdOverlay, Motion,
    QuoteOverlay, Segment, TextOverlay, Transition, VideoSpec,
)

UnitKind = str  # "still" | "card" | "video_muted" | "video_sound"


@dataclass
class Media:
    """An asset made local by `media.py`: what the compiler needs to know of it."""

    path: str
    kind: str                      # "image" | "video" | "audio" | "slate"
    duration: Optional[float] = None
    has_audio: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    # A GAM clip is its parent's bytes between two points; `offset` is where it
    # starts in the file, `length` how long it is.
    offset: float = 0.0
    length: Optional[float] = None


@dataclass
class Panel:
    kind: str                      # "quote" | "code"
    text: str
    attribution: str = ""


@dataclass
class Unit:
    segment_id: str
    segment_index: int
    first_in_segment: bool
    kind: UnitKind
    media: Optional[Media]         # None: a drawn background (a card, or no picture)
    beats: List[Beat] = field(default_factory=list)
    card: Optional[Card] = None
    # Seconds into the file and how long, for a video; None plays it whole.
    trim: Optional[Tuple[float, float]] = None
    loop: bool = True
    panel: Optional[Panel] = None
    motion: Optional[Motion] = None   # resolved, `alternate` already cycled
    fit: str = "blur"
    transition_in: Transition = field(default_factory=Transition)
    min_seconds: float = 2.5
    fixed_seconds: Optional[float] = None
    voice: Optional[str] = None
    speed: float = 1.0
    chrome: bool = True
    chapter: Optional[str] = None
    # The end credits: a card drawn from these lines rather than from `card`.
    credits: Optional[List[str]] = None
    # Seconds a clip with its sound runs past its out point, under a blend out of it
    # (`layout`). Footage after the out point where the file has it, else a held frame.
    tail: float = 0.0


def _transition_in(spec: VideoSpec, segment: Segment) -> Transition:
    """A segment's incoming join: its own fields over the project's, field by field."""
    base = spec.style.transition
    own = segment.transition_in
    if own is None:
        return base
    return Transition(style=own.style or base.style,
                      duration=own.duration if own.duration is not None else base.duration)


def _motion(spec: VideoSpec, segment: Segment, position: int) -> Optional[Motion]:
    motion = segment.visual.motion if segment.visual and segment.visual.motion else spec.style.motion
    if motion.effect == "none":
        return None
    if motion.effect == "alternate":
        return Motion(effect=KENBURNS_CYCLE[position % len(KENBURNS_CYCLE)], amount=motion.amount)
    return motion


def _panel_for(overlay: Union[QuoteOverlay, CodeOverlay]) -> Panel:
    if isinstance(overlay, QuoteOverlay):
        return Panel("quote", overlay.text, overlay.attribution or "")
    return Panel("code", overlay.text)


def _panel_beats(segment: Segment, warnings: List[str]) -> Tuple[Dict[str, Panel], Optional[Panel]]:
    """Quote and code overlays: those anchored to a beat, and one for the whole scene."""
    by_beat: Dict[str, Panel] = {}
    whole: Optional[Panel] = None
    for overlay in segment.overlays:
        if not isinstance(overlay, (QuoteOverlay, CodeOverlay)):
            # Timed text, lower thirds and images are drawn over the stitched video
            # instead (`place_overlays`), since they may run across a join.
            continue
        anchor = overlay.show.from_ if overlay.show else None
        if isinstance(anchor, AnchorRef) and anchor.beat and anchor.segment in (None, segment.id):
            by_beat[anchor.beat] = _panel_for(overlay)
        else:
            whole = _panel_for(overlay)
    return by_beat, whole


def plan_units(spec: VideoSpec, media: Dict[str, Media], warnings: List[str]) -> List[Unit]:
    """Every segment as the units it renders as, defaults resolved."""
    units: List[Unit] = []
    for seg_index, segment in enumerate(spec.segments):
        visual = segment.visual
        found = media.get(visual.asset) if visual else None
        voice = segment.narration.voice if segment.narration else None
        common = dict(
            segment_id=segment.id,
            segment_index=seg_index,
            fit=(visual.fit if visual and visual.fit else spec.style.fit),
            transition_in=_transition_in(spec, segment),
            min_seconds=(segment.duration.min if segment.duration and segment.duration.min
                         else spec.style.min_segment_seconds),
            fixed_seconds=segment.duration.fixed if segment.duration else None,
            voice=(voice.voice if voice and voice.voice else spec.voice.voice),
            speed=(voice.speed if voice and voice.speed else spec.voice.speed),
            chrome=(segment.chrome if segment.chrome is not None
                    else segment.role not in ("intro", "outro")),
        )

        trim: Optional[Tuple[float, float]] = None
        if found and found.kind == "video":
            start = found.offset + (visual.trim.in_ if visual and visual.trim else 0.0)
            if visual and visual.trim and visual.trim.out is not None:
                length = visual.trim.out - visual.trim.in_
            elif found.length is not None:
                length = found.length - (visual.trim.in_ if visual and visual.trim else 0.0)
            else:
                length = None
            if start > 0 or length is not None:
                trim = (start, max(0.1, length) if length is not None else None)

        if segment.kind == "card":
            units.append(Unit(**common, first_in_segment=True, kind="card", media=None,
                              beats=list(segment.beats), card=segment.card,
                              chapter=segment.chapter,
                              motion=(Motion(effect="zoom_in", amount=spec.style.motion.amount)
                                      if spec.style.cards.motion else None)))
            continue

        if segment.kind == "clip":
            if not found or found.kind != "video":
                warnings.append(f"Clip {segment.label or segment.id} has no video to play; left out")
                continue
            units.append(Unit(**common, first_in_segment=True, kind="video_sound", media=found,
                              trim=trim, loop=False, chapter=segment.chapter))
            continue

        if found and found.kind == "video":
            kind = "video_muted"
        else:
            kind = "still"
            if found and found.kind == "audio":
                warnings.append(f"Scene {segment.label or segment.id}: a sound file can't be its "
                                "picture; using the background")
                found = None

        by_beat, whole = _panel_beats(segment, warnings)
        groups: List[Tuple[List[Beat], Optional[Panel]]] = []
        current: List[Beat] = []
        for beat in segment.beats:
            if beat.id in by_beat:
                if current:
                    groups.append((current, whole))
                    current = []
                groups.append(([beat], by_beat[beat.id]))
            else:
                current.append(beat)
        if current or not groups:
            groups.append((current, whole))

        for position, (beats, panel) in enumerate(groups):
            units.append(Unit(
                **common, first_in_segment=position == 0, kind=kind, media=found, beats=beats,
                trim=trim, loop=visual.loop if visual else True, panel=panel,
                motion=_motion(spec, segment, len(units)) if kind == "still" else None,
                chapter=segment.chapter if position == 0 else None,
            ))
    return units


CREDITS_SEGMENT = "__credits__"
CREDIT_LINES_PER_CARD = 18


def credits_units(spec: VideoSpec, lines: Sequence[str]) -> List[Unit]:
    """The end credits as card units after everything else, one per screenful.

    Not a segment in the spec: the lines come from GAM at render time (each asset's
    credit), so the spec can't hold them, and a segment the user never made would
    show up in the editor. Past a screenful they run over several cards rather than
    shrinking to unreadable.
    """
    if not spec.credits or not spec.credits.card or not lines:
        return []
    pages = [list(lines[i:i + CREDIT_LINES_PER_CARD])
             for i in range(0, len(lines), CREDIT_LINES_PER_CARD)]
    return [
        Unit(segment_id=CREDITS_SEGMENT, segment_index=len(spec.segments),
             first_in_segment=position == 0, kind="card", media=None, credits=page,
             transition_in=spec.style.transition, min_seconds=spec.style.cards.seconds,
             chrome=False)
        for position, page in enumerate(pages)
    ]


def unit_duration(unit: Unit, narration_seconds: float, cards_seconds: float) -> float:
    """How long a unit runs, once its narration has been measured."""
    if unit.kind == "video_sound":
        if unit.trim and unit.trim[1] is not None:
            return unit.trim[1]
        return max(0.1, (unit.media.duration or 0.0) - (unit.trim[0] if unit.trim else 0.0)) \
            if unit.media else unit.min_seconds
    if unit.fixed_seconds:
        return unit.fixed_seconds
    floor = max(unit.min_seconds, cards_seconds) if unit.kind == "card" else unit.min_seconds
    return max(floor, narration_seconds)


# ── layout ──────────────────────────────────────────────────────────────────

@dataclass
class Join:
    """How unit i joins unit i-1."""

    style: str            # the spec's transition style
    duration: float       # as asked
    overlap: float = 0.0  # seconds the two share on screen: a blend's, else 0

    @property
    def is_blend(self) -> bool:
        return self.overlap > 0

    @property
    def is_cut(self) -> bool:
        return self.style == "none"


@dataclass
class Timeline:
    starts: List[float]
    durations: List[float]
    joins: List[Optional[Join]]      # joins[0] is None: nothing comes before
    total: float

    def end(self, index: int) -> float:
        return self.starts[index] + self.durations[index]


def layout(units: Sequence[Unit], durations: Sequence[float], warnings: List[str]) -> Timeline:
    """Units end to end. Each join takes the transition of the unit coming in.

    A unit after the first in its segment (a scene cut at a quote) joins with the
    project's transition, as every quote has in Notes. A blend overlaps its two units
    by its duration, held to half the shorter one so neither is ever entirely under a
    blend; too short to see, and it becomes a cut.

    A clip playing its own sound is lengthened by the blend out of it rather than
    overlapped: the stitch ends the outgoing shot's audio where the blend starts, so
    otherwise the last words before its out point would be cut. Its `tail` says by how
    much, for the renderer to extract that much more.
    """
    durations = list(durations)
    joins: List[Optional[Join]] = [None]
    for index in range(1, len(units)):
        unit = units[index]
        transition = unit.transition_in
        join = Join(style=transition.style, duration=transition.duration)
        if is_crossfade(transition.style):
            overlap = min(transition.duration, 0.5 * min(durations[index - 1], durations[index]))
            if overlap >= MIN_TRANSITION_SECONDS:
                join.overlap = overlap
            else:
                join.style = "none"
        joins.append(join)

    if sum(1 for j in joins if j and j.is_blend) and len(units) > XFADE_MAX_SHOTS:
        # One filtergraph holding every shot stops being reasonable past here;
        # Notes draws the same line. A blend degrades to a fade through black.
        warnings.append(f"Blends were drawn as fades: a video of more than {XFADE_MAX_SHOTS} "
                        "shots is too large to blend")
        for join in joins:
            if join and join.is_blend:
                join.style, join.overlap = "fade", 0.0

    for index, join in enumerate(joins):
        before = units[index - 1] if index else None
        if join is not None and join.is_blend and before is not None \
                and before.kind == "video_sound":
            before.tail = join.overlap
            durations[index - 1] += join.overlap

    starts: List[float] = []
    cursor = 0.0
    for index, duration in enumerate(durations):
        join = joins[index]
        if join is not None and join.is_blend:
            cursor -= join.overlap
        starts.append(cursor)
        cursor += duration
    return Timeline(starts=starts, durations=list(durations), joins=joins, total=max(0.0, cursor))


def xfade_name(style: str) -> str:
    return XFADE_NAMES.get(style, "dissolve")


# ── anchors ─────────────────────────────────────────────────────────────────

Spans = Dict[str, Tuple[float, float]]


@dataclass
class Placement:
    """Where things landed on the timeline, for anchors to point into."""

    segments: Spans                                   # segment id -> (start, end)
    beats: Dict[Tuple[str, str], Tuple[float, float]]  # (segment id, beat id) -> span
    total: float


def placement(units: Sequence[Unit], timeline: Timeline,
              beat_offsets: Sequence[Dict[str, Tuple[float, float]]]) -> Placement:
    """Segment and beat spans in seconds. `beat_offsets[i]` is unit i's beats, as
    offsets into that unit (from its measured narration)."""
    segments: Spans = {}
    beats: Dict[Tuple[str, str], Tuple[float, float]] = {}
    for index, unit in enumerate(units):
        start, end = timeline.starts[index], timeline.end(index)
        if unit.segment_id in segments:
            segments[unit.segment_id] = (segments[unit.segment_id][0], end)
        else:
            segments[unit.segment_id] = (start, end)
        for beat_id, (a, b) in beat_offsets[index].items():
            beats[(unit.segment_id, beat_id)] = (start + a, start + b)
    return Placement(segments=segments, beats=beats, total=timeline.total)


class Orphaned(Exception):
    """An anchor naming a segment or beat that is not in the video (any more)."""


def resolve_anchor(anchor, where: Placement, *, segment: Optional[str] = None) -> float:
    if anchor == "video_start":
        return 0.0
    if anchor == "video_end":
        return where.total
    seg = anchor.segment or segment
    if seg is None:
        raise Orphaned("an anchor names no segment")
    if anchor.beat:
        span = where.beats.get((seg, anchor.beat))
        if span is None:
            raise Orphaned(f"beat {anchor.beat!r} of segment {seg!r}")
    else:
        span = where.segments.get(seg)
        if span is None:
            raise Orphaned(f"segment {seg!r}")
    edge = span[0] if anchor.edge == "start" else span[1]
    return max(0.0, min(where.total, edge + anchor.offset))


@dataclass
class TrackPlacement:
    track: AudioTrack
    media: Media
    start: float
    length: float
    loop: bool
    duck: bool
    trim_in: float


def place_tracks(spec: VideoSpec, media: Dict[str, Media], where: Placement,
                 warnings: List[str]) -> List[TrackPlacement]:
    """Each audio track as a window on the timeline. One that cannot be placed is
    dropped with a warning, never failing the render (§5.7)."""
    placed: List[TrackPlacement] = []
    for track in spec.audio_tracks:
        found = media.get(track.asset)
        if found is None or found.kind not in ("audio", "video"):
            warnings.append(f"Audio track {track.id}: no sound to play; left out")
            continue
        try:
            start = resolve_anchor(track.start, where)
            end = resolve_anchor(track.end, where) if track.end is not None else None
        except Orphaned as exc:
            warnings.append(f"Audio track {track.id} is anchored to {exc}, which is not in "
                            "the video; left out")
            continue
        trim_in = found.offset + (track.trim.in_ if track.trim else 0.0)
        natural = None
        if found.length is not None or found.duration:
            full = found.length if found.length is not None else found.duration - found.offset
            natural = max(0.0, full - (track.trim.in_ if track.trim else 0.0))
            if track.trim and track.trim.out is not None:
                natural = min(natural, track.trim.out - track.trim.in_)
        loop = track.loop if track.loop is not None else track.kind == "music"
        if end is None:
            # "Play once to its natural end" (Notes spec doc §5.4).
            end = start + (natural or 0.0)
            loop = False
        end = min(end, where.total)
        if end - start < 0.1:
            warnings.append(f"Audio track {track.id} ends before it starts; left out")
            continue
        length = end - start
        if natural is not None and not loop:
            length = min(length, natural)
        placed.append(TrackPlacement(
            track=track, media=found, start=start, length=length, loop=loop,
            duck=(track.duck_under_narration if track.duck_under_narration is not None
                  else track.kind == "music"),
            trim_in=trim_in,
        ))
    return placed


def chapters(units: Sequence[Unit], timeline: Timeline) -> List[Tuple[float, float, str]]:
    """Chapter marks: each runs from its unit's start to the next mark."""
    marks: List[Tuple[float, str]] = [
        (timeline.starts[i], unit.chapter.strip())
        for i, unit in enumerate(units) if unit.chapter and unit.chapter.strip()
    ]
    out = []
    for position, (start, title) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else timeline.total
        out.append((start, end, title))
    return out


def beat_pause_ms(spec: VideoSpec, beats: Sequence[Beat], position: int) -> int:
    """The silence held after a beat: its own, or the default for where it sits."""
    beat = beats[position]
    if beat.pause_after_ms is not None:
        return beat.pause_after_ms
    pauses = spec.voice.pauses
    if position == len(beats) - 1:
        return pauses.segment_end_ms
    if beat.kind == "heading" or beats[position + 1].kind == "heading":
        return pauses.heading_ms
    return pauses.paragraph_ms


# ── timed overlays ──────────────────────────────────────────────────────────

TimedKind = Union[TextOverlay, LowerThirdOverlay, ImageOverlay]

DEFAULT_OVERLAY_FADE = 0.3
MIN_OVERLAY_SECONDS = 0.2


@dataclass
class OverlayPlacement:
    segment_id: str
    overlay: TimedKind
    start: float
    end: float
    fade: float
    media: Optional[Media] = None   # an image overlay's picture


def place_overlays(spec: VideoSpec, media: Dict[str, Media], where: Placement,
                   warnings: List[str]) -> List[OverlayPlacement]:
    """Text, lower thirds and images as windows on the finished timeline.

    With no `show`, an overlay covers its scene. Its anchors default to its own scene,
    so `{"edge": "start", "offset": 0.5}` means half a second into it. As with audio
    tracks, one that can't be placed is dropped with a warning (§5.7): the render
    still goes ahead.
    """
    placed: List[OverlayPlacement] = []
    for segment in spec.segments:
        span = where.segments.get(segment.id)
        name = segment.label or segment.id
        for overlay in segment.overlays:
            if not isinstance(overlay, (TextOverlay, LowerThirdOverlay, ImageOverlay)):
                continue
            if span is None:
                # The scene itself was left out (a clip with nothing to play).
                continue
            if overlay.show is None:
                start, end = span
            else:
                try:
                    start = resolve_anchor(overlay.show.from_, where, segment=segment.id)
                    end = resolve_anchor(overlay.show.to, where, segment=segment.id)
                except Orphaned as exc:
                    warnings.append(f"Scene {name}: an overlay is anchored to {exc}, which is "
                                    "not in the video; left out")
                    continue
            if end - start < MIN_OVERLAY_SECONDS:
                warnings.append(f"Scene {name}: an overlay ends before it starts; left out")
                continue
            picture = None
            if isinstance(overlay, ImageOverlay):
                picture = media.get(overlay.asset)
                if picture is None or picture.kind not in ("image", "slate"):
                    warnings.append(f"Scene {name}: an image overlay needs a picture; left out")
                    continue
            fade = overlay.fade if overlay.fade is not None else DEFAULT_OVERLAY_FADE
            # Never more than half the window each way, or the fades would cross.
            fade = max(0.0, min(fade, (end - start) / 2))
            placed.append(OverlayPlacement(segment_id=segment.id, overlay=overlay, start=start,
                                           end=end, fade=fade, media=picture))
    return placed
