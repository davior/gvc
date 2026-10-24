"""The VideoSpec: one video, described as data.

Copied from gecko-notes' `backend/app/video/spec.py` (spec 0.1), where it was proven
against a renderer that already worked: every Notes render goes through it. The design
and the reasoning are in gecko-notes' docs/gecko-video-creator.md §4–§6. Read that
before changing the shape of anything here.

What this copy does differently, and why (docs/plan-of-attack.md, "Schema changes"):

- **S1, Ken Burns framing.** `Motion` takes `effect: "path"` with a start and an end
  `Frame`, so a scene can drift from the whole map to one corner of it. The presets
  stay as shorthand.
- **S2, provenance.** `source` says whether a spec was pushed from a note or drafted
  from a brief. Either way it is a record of where the project came from, never a link
  to keep in sync: a pushed note becomes GVC's to manage.
- **S3, moments.** A `search` placeholder can ask for a moment of a given length, and
  resolves to an asset *and* an in/out point within it.
- **Limits live here.** Notes' copy stored whatever it was given and let
  `RenderOptions` clamp it at render time, so the schema carried no ranges for a UI to
  read and an out-of-range value was changed silently. Here a range is a `Field(ge,
  le)`, so an out-of-range value is refused with its path, and the JSON Schema served
  to the frontend carries the same numbers its sliders use. The ranges are the ones
  Notes clamps to, so every spec Notes produces is in range.

Pure data. Nothing here touches the filesystem, the database or a provider.
"""

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SPEC_VERSION = "0.2"


class _Model(BaseModel):
    # A spec is edited by hand and by an AI, so a misspelt field is an error rather
    # than something silently ignored. `from` and `in` are Python keywords, hence the
    # aliases below: accepted either way, and written as the spec spells them as long
    # as callers dump with `by_alias=True` (see `dump_spec`).
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ── vocabularies ────────────────────────────────────────────────────────────

Aspect = Literal["16:9", "9:16", "1:1"]
Resolution = Literal["720p", "1080p", "4k"]
Quality = Literal["preview", "standard", "high"]
Fit = Literal["blur", "pad", "crop"]
Position = Literal["top-left", "top-right", "center", "bottom-left", "bottom-right"]
VerticalPosition = Literal["top", "center", "bottom"]
WaveMode = Literal["line", "p2p", "cline", "point"]
SubtitleMode = Literal["off", "sidecar", "soft", "burn"]
OverlayTextMode = Literal["fixed", "title", "title_chapter"]
# A dip ("fade", "fadewhite") is drawn inside each shot; the rest blend two shots and
# need them to overlap on the timeline. The renderer cares, the spec does not.
TransitionStyle = Literal[
    "none", "fade", "fadewhite",
    "dissolve", "slideleft", "slideright", "wipeleft", "wiperight",
    "circleopen", "smoothleft",
]
MotionEffect = Literal[
    "none", "zoom_in", "zoom_out",
    "pan_left", "pan_right", "pan_up", "pan_down", "alternate", "path",
]
MediaType = Literal["image", "video", "audio"]

# Every text size is a percentage of the frame height, so one setting looks the same
# at 720p and 4K and in every aspect ratio.
Pct = float
Unit = Annotated[float, Field(ge=0.0, le=1.0)]


# ── assets ──────────────────────────────────────────────────────────────────

class NotesAsset(_Model):
    """A file in a note's own media, as a spec pushed from Notes refers to it.

    Only ever arrives in a pushed spec. Importing the project copies the file into GAM
    (from M1), after which nothing depends on the note.
    """

    from_: Literal["notes"] = Field(alias="from")
    url: str
    # As the note used it: a videoFile block is a video whatever its extension.
    type: MediaType
    label: Optional[str] = None


class GamAsset(_Model):
    """An asset or clip in GAM. The library is where every file GVC uses lives."""

    from_: Literal["gam"] = Field(alias="from")
    id: str
    type: Optional[MediaType] = None
    label: Optional[str] = None


class GeneratedResult(_Model):
    from_: Literal["gam"] = Field(alias="from")
    id: str


class GeneratedAsset(_Model):
    """To be generated through GAM. A preview shows it as a labelled slate."""

    from_: Literal["generate"] = Field(alias="from")
    type: Literal["image", "video", "music", "sfx"]
    prompt: str
    model: Optional[str] = None
    base_assets: List[str] = Field(default_factory=list)
    status: Literal["pending", "running", "ready", "failed"] = "pending"
    result: Optional[GeneratedResult] = None
    label: Optional[str] = None
    # "16:9" etc.; unset, the video's own aspect. Only read when generating.
    aspect: Optional[Aspect] = None

    @model_validator(mode="after")
    def _ready_has_result(self) -> "GeneratedAsset":
        if self.status == "ready" and self.result is None:
            raise ValueError('a generated asset marked "ready" needs its result')
        return self


class Moment(_Model):
    """How long a found moment should be (S3). Either bound may be left open."""

    min: Optional[float] = Field(default=None, gt=0)
    max: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Moment":
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError("moment.max is shorter than moment.min")
        return self


class SearchResult(_Model):
    from_: Literal["gam"] = Field(alias="from")
    id: str
    # Where in the asset the found moment is. Set when the search asked for a moment;
    # resolving copies them into the visual's trim (S3).
    in_: Optional[float] = Field(default=None, alias="in", ge=0)
    out: Optional[float] = Field(default=None, ge=0)


class SearchAsset(_Model):
    """Footage still to be found in GAM: "where people talk about X"."""

    from_: Literal["search"] = Field(alias="from")
    query: str
    type: Optional[MediaType] = None
    # Present: find a moment inside an asset, not just an asset.
    moment: Optional[Moment] = None
    status: Literal["unresolved", "resolved"] = "unresolved"
    result: Optional[SearchResult] = None
    label: Optional[str] = None


AssetRef = Annotated[
    Union[NotesAsset, GamAsset, GeneratedAsset, SearchAsset],
    Field(discriminator="from_"),
]


# ── project-wide settings ───────────────────────────────────────────────────

class Output(_Model):
    aspect: Aspect = "16:9"
    resolution: Resolution = "1080p"
    quality: Quality = "standard"
    fps: int = Field(default=30, ge=12, le=60)
    subtitles: SubtitleMode = "sidecar"
    chapters: bool = True               # embed chapter marks in the file
    thumbnail: bool = True


class Pauses(_Model):
    paragraph_ms: int = Field(default=350, ge=0, le=3000)
    heading_ms: int = Field(default=800, ge=0, le=5000)
    segment_end_ms: int = Field(default=600, ge=0, le=3000)


class Voice(_Model):
    # None means "whatever the account is set to"; naming one pins it for the video.
    provider: Optional[Literal["auto", "deepgram", "fal"]] = None
    voice: Optional[str] = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    expressivity: Optional[int] = Field(default=None, ge=-2, le=2)  # Deepgram Flux only
    pauses: Pauses = Field(default_factory=Pauses)


class VoiceOverride(_Model):
    """A segment's voice: any field left out comes from the project's."""

    provider: Optional[Literal["auto", "deepgram", "fal"]] = None
    voice: Optional[str] = None
    speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
    expressivity: Optional[int] = Field(default=None, ge=-2, le=2)


class Transition(_Model):
    """How the previous segment gives way to this one."""

    style: TransitionStyle = "none"
    # Seconds. A dip spends this long out and the same back in; a blend overlaps the
    # two segments by it. The renderer may shorten it to fit a short segment.
    duration: float = Field(default=0.6, ge=0.1, le=3.0)


class TransitionOverride(_Model):
    """A segment's `transition_in`: any field left out comes from `style.transition`.

    Field by field rather than whole-object (the Notes spec doc, open decision 13),
    because "dissolve into this scene" should not have to restate the project's
    duration, and an AI asked for exactly that will not.
    """

    style: Optional[TransitionStyle] = None
    duration: Optional[float] = Field(default=None, ge=0.1, le=3.0)


class Frame(_Model):
    """A crop of the source picture, in fractions of its width and height (S1).

    Fractions so a frame survives swapping the picture for a larger copy, and so "the
    left third" can be said without knowing the resolution. No height: it follows from
    the output's aspect ratio, so a frame can never ask for a stretched picture.
    """

    x: Unit                             # left edge
    y: Unit                             # top edge
    w: float = Field(gt=0.0, le=1.0)    # width; 1.0 is the whole picture

    @model_validator(mode="after")
    def _inside(self) -> "Frame":
        if self.x + self.w > 1.0 + 1e-9:
            raise ValueError("frame runs off the right edge of the picture (x + w > 1)")
        # The bottom edge depends on the picture's and the output's aspect ratios, which
        # the spec does not know, so it is checked at render time, not here.
        return self


class Motion(_Model):
    """A Ken Burns move over a still."""

    effect: MotionEffect = "none"       # "alternate" only makes sense project-wide
    amount: float = Field(default=0.12, ge=0.02, le=0.5)   # presets only
    # effect "path" only: the camera starts on `from` and ends on `to`.
    from_: Optional[Frame] = Field(default=None, alias="from")
    to: Optional[Frame] = None
    # Unset: "in_out" for a path, "linear" for a preset (which is how Notes drew them).
    ease: Optional[Literal["linear", "in_out"]] = None

    @model_validator(mode="after")
    def _path_has_frames(self) -> "Motion":
        if self.effect == "path":
            if self.from_ is None or self.to is None:
                raise ValueError('effect "path" needs both "from" and "to" frames')
        elif self.from_ is not None or self.to is not None:
            raise ValueError('"from" and "to" frames are only read with effect "path"')
        return self


class Background(_Model):
    """Shown behind a segment that has no visual of its own."""

    type: Literal["gradient", "solid", "image"] = "gradient"
    colors: List[str] = Field(default_factory=lambda: ["#1e293b", "#0f172a"], min_length=1)
    angle: int = 135
    asset: Optional[str] = None         # used when type == "image"


class CardText(_Model):
    title_pct: Pct = Field(default=6.8, ge=1.0, le=25.0)
    subtitle_pct: Pct = Field(default=2.9, ge=0.5, le=15.0)


class Cards(_Model):
    seconds: float = Field(default=3.5, ge=0.5, le=30.0)
    motion: bool = False                # Ken Burns on cards (zoom only)
    title: CardText = Field(default_factory=CardText)
    chapter: CardText = Field(default_factory=CardText)


class QuoteStyle(_Model):
    position: VerticalPosition = "center"
    size_pct: Pct = Field(default=4.2, ge=1.0, le=15.0)
    color: str = "#ffffff"
    accent: str = "#818cf8"
    scrim: Unit = 0.55


class CodeStyle(_Model):
    position: VerticalPosition = "center"
    size_pct: Pct = Field(default=3.4, ge=1.0, le=12.0)
    color: str = "#e2e8f0"
    scrim: Unit = 0.72


class Style(_Model):
    background: Background = Field(default_factory=Background)
    fit: Fit = "blur"
    motion: Motion = Field(default_factory=Motion)
    transition: Transition = Field(default_factory=Transition)
    min_segment_seconds: float = Field(default=2.5, ge=0.5, le=30.0)
    cards: Cards = Field(default_factory=Cards)
    quote: QuoteStyle = Field(default_factory=QuoteStyle)
    code: CodeStyle = Field(default_factory=CodeStyle)


class Watermark(_Model):
    asset: Optional[str] = None
    text: str = ""                      # empty: "by {title}"
    position: Position = "bottom-right"
    opacity: Unit = 0.85
    scale_pct: Pct = Field(default=6.0, ge=1.0, le=30.0)
    caption_pct: Pct = Field(default=2.3, ge=0.5, le=15.0)
    margin_pct: int = Field(default=4, ge=0, le=25)


class OverlayText(_Model):
    mode: OverlayTextMode = "fixed"
    text: str = ""
    position: Position = "bottom-left"
    color: str = "#ffffff"
    size_pct: Pct = Field(default=3.0, ge=0.5, le=20.0)
    margin_pct: int = Field(default=5, ge=0, le=25)
    shadow: bool = True


class Waveform(_Model):
    mode: WaveMode = "line"
    color: str = "#00ff41"
    opacity: Unit = 0.7
    position: VerticalPosition = "bottom"
    height_pct: int = Field(default=22, ge=1, le=100)
    scrim: Unit = 0.45


class Chrome(_Model):
    """Drawn over every segment that doesn't opt out. A block present means on."""

    watermark: Optional[Watermark] = None
    overlay_text: Optional[OverlayText] = None
    waveform: Optional[Waveform] = None


# ── time ────────────────────────────────────────────────────────────────────

class AnchorRef(_Model):
    """A moment defined by the structure rather than by a number of seconds.

    This is what lets a soundtrack "start at the caravans and end after the market"
    and still land on the right cut after a scene is inserted in between.
    """

    segment: Optional[str] = None       # inside a segment's overlay: that segment
    beat: Optional[str] = None
    edge: Literal["start", "end"]
    offset: float = 0.0                 # seconds; negative is before the edge


Anchor = Union[Literal["video_start", "video_end"], AnchorRef]


class Span(_Model):
    from_: Anchor = Field(alias="from")
    to: Anchor


class Trim(_Model):
    in_: float = Field(alias="in", ge=0)
    out: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Trim":
        if self.out is not None and self.out <= self.in_:
            raise ValueError("trim.out must come after trim.in")
        return self


# ── segments ────────────────────────────────────────────────────────────────

class MotionOverride(Motion):
    """A segment's own Ken Burns move.

    Whole-object, unlike `TransitionOverride`: a move is one idea ("zoom into the
    oasis"), and inheriting half of the project's ("its amount, my effect") would make
    a path whose frames came from one place and whose easing came from another.
    """


class Visual(_Model):
    asset: str
    fit: Optional[Fit] = None
    motion: Optional[MotionOverride] = None   # stills only
    trim: Optional[Trim] = None               # videos only
    audio: Literal["mute", "play"] = "mute"   # "play" only on a clip
    loop: bool = True                         # shorter than its segment: loop, or hold
    # A clip's sound is matched to the narration's loudness by the renderer; this
    # moves it from there, in dB (S5). Ignored where the footage plays muted.
    volume_db: Optional[float] = Field(default=None, ge=-30, le=20)


class Beat(_Model):
    """One spoken unit: a line or a paragraph of the script."""

    id: str
    text: str                           # [pause:…] markup is kept and honoured
    kind: Literal["prose", "heading", "quote", "code"] = "prose"
    speak: bool = True                  # False: timed, but silent
    hold: Optional[float] = Field(default=None, ge=0)  # seconds a silent beat lasts
    pause_after_ms: Optional[int] = Field(default=None, ge=0, le=10000)
    # The note block it was read from, when pushed from Notes. Provenance only.
    block_id: Optional[str] = None


class Narration(_Model):
    beats: List[Beat] = Field(default_factory=list)
    voice: Optional[VoiceOverride] = None


class _OverlayBase(_Model):
    id: str
    show: Optional[Span] = None         # default: the whole segment
    fade: Optional[float] = Field(default=None, ge=0, le=5)


class QuoteOverlay(_OverlayBase):
    type: Literal["quote"]
    text: str
    attribution: Optional[str] = None


class CodeOverlay(_OverlayBase):
    type: Literal["code"]
    text: str
    language: Optional[str] = None


class TextOverlay(_OverlayBase):
    type: Literal["text"]
    text: str
    position: Position = "center"
    size_pct: Optional[Pct] = Field(default=None, ge=0.5, le=25.0)
    color: Optional[str] = None


class LowerThirdOverlay(_OverlayBase):
    type: Literal["lower_third"]
    title: str
    subtitle: Optional[str] = None


class ImageOverlay(_OverlayBase):
    type: Literal["image"]
    asset: str
    position: Position = "center"
    scale_pct: Optional[Pct] = Field(default=None, ge=1.0, le=100.0)
    opacity: Optional[Unit] = None


class WaveformOverlay(_OverlayBase):
    """An animated audio wave across the frame for as long as the overlay shows.

    The same settings, with the same ranges, as the project-wide `chrome.waveform`
    (which is what Notes draws across a whole video). It draws what the video itself is
    playing at that moment (narration, or a clip's own sound), so it needs no asset.
    """

    type: Literal["waveform"]
    mode: WaveMode = "line"
    color: str = "#00ff41"
    opacity: Unit = 0.7
    position: VerticalPosition = "bottom"
    height_pct: int = Field(default=22, ge=1, le=100)
    scrim: Unit = 0.45


Overlay = Annotated[
    Union[QuoteOverlay, CodeOverlay, TextOverlay, LowerThirdOverlay, ImageOverlay,
          WaveformOverlay],
    Field(discriminator="type"),
]


class Card(_Model):
    variant: Literal["title", "chapter"]
    title: str
    subtitle: Optional[str] = None


class Duration(_Model):
    min: Optional[float] = Field(default=None, gt=0)
    fixed: Optional[float] = Field(default=None, gt=0)


class SegmentSource(_Model):
    """The note blocks a pushed segment came from. Provenance only."""

    block_ids: List[str] = Field(default_factory=list)


class Segment(_Model):
    id: str
    # scene: a visual with narration over it. card: a title or chapter screen.
    # clip: a video played with its own sound and no narration.
    kind: Literal["scene", "card", "clip"]
    role: Optional[Literal["title", "intro", "outro"]] = None
    label: str = ""
    chapter: Optional[str] = None       # a chapter mark at this segment's start
    visual: Optional[Visual] = None
    card: Optional[Card] = None
    narration: Optional[Narration] = None
    overlays: List[Overlay] = Field(default_factory=list)
    transition_in: Optional[TransitionOverride] = None
    duration: Optional[Duration] = None
    # None: the default, which is on except for an intro or outro.
    chrome: Optional[bool] = None
    source: Optional[SegmentSource] = None

    @property
    def beats(self) -> List[Beat]:
        return self.narration.beats if self.narration is not None else []


class AudioTrack(_Model):
    """Music, a sound effect or extra voice, from one anchor to another.

    Changing the soundtrack through a video is several of these. A crossfade is two
    that overlap (a negative `offset` on the second's start) with matching fades.
    """

    id: str
    kind: Literal["music", "sfx", "voiceover"] = "music"
    asset: str
    start: Anchor
    end: Optional[Anchor] = None        # None: play once, to its natural end
    trim: Optional[Trim] = None
    loop: Optional[bool] = None         # default: on for music
    volume: Unit = 0.18
    duck_under_narration: Optional[bool] = None   # default: on for music
    # While a clip plays its own sound (S5). None: as under narration (a ducked
    # track dips, one that isn't plays on). "mute" fades it out for the clip and
    # back in after; "play" keeps it at its level, ducked under narration only.
    during_clips: Optional[Literal["mute", "play"]] = None
    fade_in: float = Field(default=0.0, ge=0, le=15)
    fade_out: float = Field(default=0.0, ge=0, le=15)


class Credits(_Model):
    auto: bool = True
    card: bool = True
    description: bool = True
    extra: List[str] = Field(default_factory=list)


class NoteSource(_Model):
    """Pushed from a note in Gecko Notes (S2). Provenance only: GVC never re-reads it."""

    kind: Literal["note"]
    note_id: Optional[str] = None
    note_version_id: Optional[str] = None
    imported_at: Optional[str] = None   # ISO 8601
    selection: bool = False             # only part of the note was pushed


class BriefSource(_Model):
    """Drafted by an AI from a prompt (S2). Kept so a draft can be traced and redone."""

    kind: Literal["brief"]
    prompt: str
    asset_ids: List[str] = Field(default_factory=list)  # GAM assets it started from
    drafted_at: Optional[str] = None    # ISO 8601
    provider: Optional[str] = None
    model: Optional[str] = None


SpecSource = Annotated[Union[NoteSource, BriefSource], Field(discriminator="kind")]


class VideoSpec(_Model):
    spec_version: Literal["0.2"] = SPEC_VERSION
    id: Optional[str] = None
    title: str = ""
    # None: made by hand in GVC.
    source: Optional[SpecSource] = None
    output: Output = Field(default_factory=Output)
    voice: Voice = Field(default_factory=Voice)
    style: Style = Field(default_factory=Style)
    chrome: Chrome = Field(default_factory=Chrome)
    assets: Dict[str, AssetRef] = Field(default_factory=dict)
    segments: List[Segment] = Field(default_factory=list)
    audio_tracks: List[AudioTrack] = Field(default_factory=list)
    credits: Optional[Credits] = None

    @model_validator(mode="after")
    def _well_formed(self) -> "VideoSpec":
        """The structural rules (the Notes spec doc §5.7).

        Anchors are deliberately not checked: removing a segment something is anchored
        to is allowed, and what an orphaned anchor means is the renderer's call (it
        drops the element with a warning). A save must never be blocked by it.
        """
        problems: List[str] = []

        def unique(ids: List[str], what: str) -> None:
            seen = set()
            for value in ids:
                if value in seen:
                    problems.append(f"duplicate {what} id {value!r}")
                seen.add(value)

        def known(key: Optional[str], where: str) -> None:
            if key is not None and key not in self.assets:
                problems.append(f"{where} refers to unknown asset {key!r}")

        unique([s.id for s in self.segments], "segment")
        unique([t.id for t in self.audio_tracks], "audio track")
        known(self.style.background.asset, "style.background")
        if self.style.motion.effect == "path":
            # A path is a frame on one particular picture; as the project's default it
            # would aim every still at the same corner.
            problems.append('style.motion cannot be a "path"; set it on a segment')
        if self.chrome.watermark is not None:
            known(self.chrome.watermark.asset, "chrome.watermark")
        for key, asset in self.assets.items():
            for base in getattr(asset, "base_assets", []):
                known(base, f"asset {key!r}")
        for segment in self.segments:
            where = f"segment {segment.id!r}"
            unique([b.id for b in segment.beats], f"{where} beat")
            unique([o.id for o in segment.overlays], f"{where} overlay")
            if segment.visual is not None:
                known(segment.visual.asset, where)
                motion = segment.visual.motion
                if motion is not None and motion.effect == "alternate":
                    problems.append(f'{where}: "alternate" only makes sense project-wide')
            for overlay in segment.overlays:
                if isinstance(overlay, ImageOverlay):
                    known(overlay.asset, f"{where} overlay {overlay.id!r}")
            if segment.kind == "card" and segment.card is None:
                problems.append(f"{where} is a card with no card")
            if segment.kind != "card" and segment.card is not None:
                problems.append(f"{where} has a card but is a {segment.kind}")
            if segment.kind == "clip" and segment.visual is None:
                problems.append(f"{where} is a clip with no visual")
        for track in self.audio_tracks:
            known(track.asset, f"audio track {track.id!r}")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def dump_spec(spec: VideoSpec) -> dict:
    """The spec as JSON-ready data, spelt the way the format spells it.

    `by_alias` writes `from` / `in` rather than `from_` / `in_`. `exclude_none` keeps a
    stored spec to what was actually said: "a block absent means off" is part of the
    format (the Notes spec doc, principle 5), so writing `"watermark": null` back out
    would be noise at best.
    """
    return spec.model_dump(mode="json", by_alias=True, exclude_none=True)
