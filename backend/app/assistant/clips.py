"""The clip-picking pass: one video's whole transcript read against one idea.

A separate model call, not more reading in the turn's own conversation, for two reasons.
Everything the turn reads stays in its conversation and is sent again every round, so
reading five hour-long interviews there costs five transcripts times every round left;
here each is read once and only the chosen passages come back. And a call with nothing
to do but answer "where in this does someone make this point best" judges the passage,
where the turn's model is busy writing a video.

The picker names lines by number, never by time. The times come from the transcript, so
a cut can't land on a moment the picker made up.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    # tools.py imports this module, so only for the annotations.
    from app.assistant.tools import Sentence

# What one picker call reads: about 15k tokens. A longer transcript is read in windows
# and the best passages of all of them kept.
MAX_PICK_CHARS = 60_000
# Lines each window repeats from the one before, so a passage that straddles the edge
# is whole in one of them.
WINDOW_OVERLAP = 6
# Longer than this is a scene, not a clip; the picker is told so, and held to it.
MAX_CLIP_SECONDS = 90.0

SYSTEM = """\
You pick clips for a video editor. You are given one video's transcript, one sentence \
per numbered line with its [start-end] seconds, and the idea a scene has to put across.

Find the passages where the speaker demonstrates that idea best: a complete thought, \
said clearly, that makes sense to a viewer who hasn't seen the rest of the video. Prefer \
the clearest, most concrete or most striking statement to the first or longest mention. \
A passage is one or more consecutive lines, usually 5-40 seconds and never over 90. Start \
it where the thought starts, not mid-argument, and end it where the thought lands.

Answer with JSON only: an array, best first, of \
{"first": line, "last": line, "score": 1-10, "why": "one short sentence"}. \
score is how well the passage makes the point (10: exactly this, said perfectly; 5: \
touches on it; below 4: don't include it). An empty array when nothing makes the point."""


@dataclass
class Clip:
    first: int
    last: int
    score: float
    why: str


def windows(lines: Sequence[Sentence]) -> List[Tuple[int, int]]:
    """[start, end) line ranges of at most MAX_PICK_CHARS each, overlapping a little."""
    out: List[Tuple[int, int]] = []
    start = 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (end == start or size + len(lines[end].text) + 20
                                    <= MAX_PICK_CHARS):
            size += len(lines[end].text) + 20
            end += 1
        out.append((start, end))
        if end >= len(lines):
            break
        start = max(start + 1, end - WINDOW_OVERLAP)
    return out


def prompt_for(idea: str, count: int, lines: Sequence[Sentence], window: Tuple[int, int],
               name: Optional[str] = None) -> str:
    start, end = window
    numbered = "\n".join(f"{i} [{lines[i].start:.1f}-{lines[i].end:.1f}] {lines[i].text}"
                         for i in range(start, end))
    part = (f" (lines {start}-{end - 1} of {len(lines)}; the rest is read separately)"
            if start > 0 or end < len(lines) else "")
    return (f"The idea: {idea.strip()}\n\n"
            f"Up to {count} passages.\n\n"
            f"Transcript of {name or 'the video'}{part}:\n{numbered}")


def _array(text: str) -> List[Any]:
    """The JSON array in a reply, which a model may wrap in prose or a code fence."""
    match = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not match:
        return []
    try:
        found = json.loads(match.group(0))
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def parse(text: str, lines: Sequence[Sentence], window: Tuple[int, int]) -> List[Clip]:
    """The picker's passages that name real lines in its window and fit the rules.

    Anything else is dropped rather than repaired: a line number out of range is a
    passage the picker didn't read, and stretching or clamping it would cut something
    nobody chose.
    """
    start, end = window
    out: List[Clip] = []
    for item in _array(text):
        if not isinstance(item, dict):
            continue
        try:
            first, last = int(item["first"]), int(item["last"])
            score = float(item.get("score", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if not (start <= first <= last < end):
            continue
        if lines[last].end - lines[first].start > MAX_CLIP_SECONDS or score < 4:
            continue
        out.append(Clip(first, last, min(score, 10.0), str(item.get("why") or "")[:200]))
    return out


def best(found: Sequence[Clip], count: int) -> List[Clip]:
    """The highest-scoring passages, no two overlapping, in the order they were said.

    Overlap happens where windows share lines, and when a picker offers the same
    thought cut two ways; either way the viewer would see it twice.
    """
    kept: List[Clip] = []
    for clip in sorted(found, key=lambda c: (-c.score, c.first)):
        if all(clip.last < k.first or clip.first > k.last for k in kept):
            kept.append(clip)
        if len(kept) == count:
            break
    return sorted(kept, key=lambda c: c.first)
