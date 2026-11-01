"""A video's script as a Word document: every word the video says, in order.

For reading a video through for flow before rendering it, or with a pen. The
document lists each segment under a heading. A segment shows the narration it reads
out, the words its card or overlays put on screen, and, for a clip, what the people
in the footage say between its in and out points, from GAM's transcript.

Read-only, and one-way. Edits made in the document are not read back: the spec stays
the only place a video is defined (the same rule as a pushed note, D3).

Two halves, so the document can be tested without GAM: `clip_texts` asks GAM for
what each clip says, and `build_docx` lays out a spec and those texts.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Cm, Pt, RGBColor

from app.clock import utcnow
from app.gam.client import GamClient, GamError
from app.render.pause_markup import _MARKER_ONLY
from app.schemas_gam import GamTranscript
from app.spec.model import (
    Beat, CodeOverlay, GamAsset, GeneratedAsset, LowerThirdOverlay, NotesAsset,
    QuoteOverlay, SearchAsset, Segment, TextOverlay, VideoSpec,
)

# A narrator's pace at speed 1.0, for the read-through time the summary line gives.
# Rough on purpose: the point is "about four minutes", not a render estimate.
WORDS_PER_MINUTE = 150

GREY = RGBColor(0x6B, 0x72, 0x80)
CLIP_COLOUR = RGBColor(0x1D, 0x4E, 0xD8)


@dataclass
class Said:
    """One speaker's run of words inside a clip."""

    text: str
    speaker: Optional[int] = None


@dataclass
class ClipText:
    """What a clip segment says, or why it can't be shown."""

    name: str = ""
    start: Optional[float] = None       # seconds into the source the window covers
    end: Optional[float] = None
    said: List[Said] = field(default_factory=list)
    # Set when there is nothing to show: footage still to find, a transcript GAM
    # doesn't have, the library unreachable. Said in the document, so a gap in the
    # script is explained rather than silently missing.
    problem: Optional[str] = None


# ── reading clips from GAM ──────────────────────────────────────────────────

def _gam_id(spec: VideoSpec, key: str) -> Tuple[Optional[str], Optional[str]]:
    """The GAM id behind an asset key, or why there isn't one."""
    ref = spec.assets.get(key)
    if ref is None:
        return None, "This clip's footage isn't in the project."
    if isinstance(ref, GamAsset):
        return ref.id, None
    if isinstance(ref, SearchAsset):
        if ref.result is None:
            return None, f"Footage still to find: “{ref.query}”."
        return ref.result.id, None
    if isinstance(ref, GeneratedAsset):
        if ref.result is None:
            return None, "Footage still to generate."
        return ref.result.id, None
    if isinstance(ref, NotesAsset):
        return None, "This clip is still in the note it came from; copy it into GAM first."
    return None, "This clip's footage isn't in the asset library."


def words_between(transcript: GamTranscript, start: float, end: Optional[float]) -> List[Said]:
    """The words spoken between two points of a recording, grouped by speaker.

    Word by word rather than sentence by sentence (unlike the assistant's
    `sentences`), because this is for checking what the cut actually says, and a
    trim that starts mid-sentence should read as one. A word counts when its middle
    falls inside the window, so a word clipped by a frame either side doesn't vanish
    or double up between two clips cut back to back.

    A segment corrected by hand in GAM, or one with no word timings, is read whole
    when its middle is inside: its words may no longer spell its text.
    """
    def inside(a: float, b: float) -> bool:
        middle = (a + b) / 2
        return middle >= start and (end is None or middle < end)

    out: List[Said] = []
    for segment in transcript.segments:
        words = [] if segment.edited else [w for w in segment.words if w.text.strip()]
        if words:
            picked = [w.text.strip() for w in words if inside(w.start_time, w.end_time)]
        elif segment.text.strip() and inside(segment.start_time, segment.end_time):
            picked = [segment.text.strip()]
        else:
            picked = []
        if not picked:
            continue
        if out and out[-1].speaker == segment.speaker:
            out[-1].text += " " + " ".join(picked)
        else:
            out.append(Said(" ".join(picked), segment.speaker))
    return out


def clip_texts(spec: VideoSpec, gam: GamClient) -> Dict[str, ClipText]:
    """What every clip segment says, by segment id.

    Only `clip` segments: they're the ones that play their own sound. A scene's
    footage always plays muted under the narration (`compile.plan_units`), so its
    transcript is never heard and doesn't belong in the script.

    A GAM failure becomes that clip's `problem` rather than failing the export: the
    narration is the larger part of a script and is worth having on its own. Once GAM
    is unreachable it isn't asked again, so a dead library costs one timeout, not one
    per clip.
    """
    out: Dict[str, ClipText] = {}
    down: Optional[str] = None
    transcripts: Dict[str, Optional[GamTranscript]] = {}
    for segment in spec.segments:
        if segment.kind != "clip" or segment.visual is None:
            continue
        visual = segment.visual
        gam_id, problem = _gam_id(spec, visual.asset)
        if gam_id is None:
            out[segment.id] = ClipText(problem=problem)
            continue
        if down is not None:
            out[segment.id] = ClipText(problem=down)
            continue
        try:
            asset = gam.get_asset(gam_id)
            if asset is None:
                out[segment.id] = ClipText(problem="This clip is no longer in the asset library.")
                continue
            # A GAM clip is a window on its parent and has no transcript of its own
            # (GAM transcribes the file, and a clip has none until it is extracted), so
            # its words are the parent's between the clip's points. The spec's trim is
            # then relative to the clip, as the renderer reads it (`media.offset`).
            source_id, offset, cap = asset.id, 0.0, None
            if asset.parent_asset_id and asset.in_point is not None:
                source_id, offset, cap = asset.parent_asset_id, asset.in_point, asset.out_point
            start = offset + (visual.trim.in_ if visual.trim else 0.0)
            end = offset + visual.trim.out if visual.trim and visual.trim.out is not None else cap
            if cap is not None and end is not None:
                end = min(end, cap)
            if source_id not in transcripts:
                transcripts[source_id] = gam.transcript(source_id)
            transcript = transcripts[source_id]
        except GamError as exc:
            down = f"The asset library couldn't be read: {exc.message}"
            out[segment.id] = ClipText(problem=down)
            continue
        text = ClipText(name=asset.name, start=start, end=end)
        if transcript is None or not transcript.segments:
            text.problem = "This clip hasn't been transcribed in the asset library."
        else:
            text.said = words_between(transcript, start, end)
            if not text.said:
                text.problem = "Nothing is said in this clip."
        out[segment.id] = text
    return out


# ── the document ────────────────────────────────────────────────────────────

def _clock(seconds: float) -> str:
    whole = int(round(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _words(text: str) -> int:
    return len(_MARKER_ONLY.sub(" ", text).split())


def _segment_heading(position: int, segment: Segment, clip: Optional[ClipText]) -> str:
    if segment.kind == "card" and segment.card is not None:
        kind = "Title card" if segment.card.variant == "title" else "Chapter card"
        name = segment.label or segment.card.title
    elif segment.kind == "clip":
        kind = "Clip"
        name = segment.label or (clip.name if clip else "")
    else:
        kind = {"intro": "Intro", "outro": "Outro"}.get(segment.role or "", "Scene")
        name = segment.label
    return f"{position}. {kind}" + (f": {name}" if name and name != kind else "")


def _note(doc, text: str, *, italic: bool = True):
    """A line about the video rather than words in it: smaller and grey."""
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.italic = italic
    run.font.size = Pt(9)
    run.font.color.rgb = GREY
    return paragraph


def _spoken(paragraph, text: str, *, bold=False, italic=False, mono=False) -> None:
    """Narration text, with its `[pause]` marks kept but greyed.

    Kept rather than stripped: they change how a line lands when read aloud, which is
    exactly what a read-through is checking.
    """
    position = 0
    for match in _MARKER_ONLY.finditer(text):
        _run(paragraph, text[position:match.start()], bold, italic, mono)
        mark = paragraph.add_run(match.group(0))
        mark.font.size = Pt(8)
        mark.font.color.rgb = GREY
        position = match.end()
    _run(paragraph, text[position:], bold, italic, mono)


def _run(paragraph, text: str, bold: bool, italic: bool, mono: bool) -> None:
    if not text:
        return
    # A blank line in a beat is a paragraph break the voice pauses on; a line break
    # keeps it visible without splitting the beat into two paragraphs.
    for n, line in enumerate(text.split("\n")):
        if n:
            paragraph.add_run().add_break(WD_BREAK.LINE)
        if line:
            run = paragraph.add_run(line)
            run.bold, run.italic = bold, italic
            if mono:
                run.font.name = "Consolas"


def _beat(doc, beat: Beat) -> None:
    style = "Quote" if beat.kind == "quote" else None
    paragraph = doc.add_paragraph(style=style)
    if not beat.speak:
        label = paragraph.add_run("On screen, not spoken: ")
        label.font.size = Pt(9)
        label.font.color.rgb = GREY
    _spoken(paragraph, beat.text, bold=beat.kind == "heading",
            italic=beat.kind == "quote", mono=beat.kind == "code")


def _on_screen(segment: Segment) -> List[str]:
    """The words a segment's overlays put on screen."""
    lines: List[str] = []
    for overlay in segment.overlays:
        if isinstance(overlay, LowerThirdOverlay):
            lines.append(overlay.title + (f" / {overlay.subtitle}" if overlay.subtitle else ""))
        elif isinstance(overlay, QuoteOverlay):
            lines.append(f"“{overlay.text}”" + (f" ({overlay.attribution})" if overlay.attribution else ""))
        elif isinstance(overlay, (TextOverlay, CodeOverlay)) and overlay.text.strip():
            lines.append(overlay.text)
    return lines


def _clip(doc, clip: Optional[ClipText]) -> None:
    if clip is None:
        _note(doc, "This clip has no footage set.")
        return
    if clip.start is not None:
        span = _clock(clip.start) + "–" + (_clock(clip.end) if clip.end is not None else "end")
        _note(doc, f"From “{clip.name}”, {span}" if clip.name else span)
    if clip.problem:
        _note(doc, clip.problem)
        return
    speakers = len({s.speaker for s in clip.said if s.speaker is not None}) > 1
    for said in clip.said:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(1)
        if speakers:
            who = paragraph.add_run(f"Speaker {said.speaker + 1 if said.speaker is not None else '?'}: ")
            who.bold = True
            who.font.color.rgb = CLIP_COLOUR
        run = paragraph.add_run(said.text)
        run.font.color.rgb = CLIP_COLOUR


def build_docx(spec: VideoSpec, clips: Dict[str, ClipText]) -> bytes:
    doc = Document()
    doc.core_properties.title = spec.title or "Untitled video"
    doc.add_heading(spec.title or "Untitled video", level=0)

    narrated = sum(_words(b.text) for s in spec.segments for b in s.beats if b.speak)
    quoted = sum(len(said.text.split()) for c in clips.values() for said in c.said)
    minutes = narrated / (WORDS_PER_MINUTE * spec.voice.speed) if narrated else 0
    today = utcnow()
    count = len(spec.segments)
    summary = (f"Script, exported {today.day} {today:%B %Y}. "
               f"{count} segment{'' if count == 1 else 's'}; {narrated} words of narration")
    if narrated:
        summary += f" (about {max(1, round(minutes))} min read aloud)"
    if clips:
        summary += f" and {quoted} words said in clips"
    _note(doc, summary + ".", italic=False)
    _note(doc, "Narration is in black. What is said in clips is indented in blue. "
               "Grey is what is on screen or a note about the video, not spoken.")

    for position, segment in enumerate(spec.segments, start=1):
        if segment.chapter:
            doc.add_heading(segment.chapter, level=1)
        clip = clips.get(segment.id)
        doc.add_heading(_segment_heading(position, segment, clip), level=2)

        if segment.card is not None:
            text = segment.card.title + (f" / {segment.card.subtitle}" if segment.card.subtitle else "")
            _note(doc, f"On screen: {text}", italic=False)
        for line in _on_screen(segment):
            _note(doc, f"On screen: {line}", italic=False)

        if segment.kind == "clip":
            _clip(doc, clip)
        for beat in segment.beats:
            _beat(doc, beat)
        if segment.kind == "scene" and not segment.beats:
            _note(doc, "No narration.")

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


_UNSAFE = re.compile(r"[^\w\- ]+", re.UNICODE)


def filename(spec: VideoSpec) -> str:
    stem = _UNSAFE.sub("", spec.title).strip().replace(" ", "-")[:80] or "video"
    return f"{stem}-script.docx"
