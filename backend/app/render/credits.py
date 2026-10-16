"""What the end credits and the description say.

Credits come from GAM: each asset's `credit`, which GAM builds from its attribution
fields (and a clip inherits from its parent). GVC keeps no attribution of its own, so
correcting a credit is done once, in the library, and every video using it follows.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from app.render.media import keys_in_order
from app.spec.model import VideoSpec


def credit_lines(spec: VideoSpec, credits: Dict[str, str]) -> List[str]:
    """The credits, in the order their assets first appear, each said once."""
    if spec.credits is None:
        return []
    lines: List[str] = []
    if spec.credits.auto:
        lines += [credits.get(key, "").strip() for key in keys_in_order(spec)]
    lines += [line.strip() for line in spec.credits.extra]
    # One credit line for a photographer's three pictures, not three.
    return list(dict.fromkeys(line for line in lines if line))


def _clock(seconds: float) -> str:
    whole = int(round(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def description_text(spec: VideoSpec, lines: Sequence[str],
                     marks: Sequence[Tuple[float, float, str]]) -> str:
    """Text to paste under the video where it is published: chapters and credits.

    Chapters are listed as `0:00 Title`, the form video sites turn into chapter
    links, and only with the first at 0:00, which those sites require.
    """
    parts: List[str] = []
    if spec.output.chapters and marks:
        listed = [(start, title) for start, _end, title in marks]
        if listed[0][0] > 0.5:
            listed.insert(0, (0.0, spec.title or "Start"))
        parts.append("\n".join(f"{_clock(start)} {title}" for start, title in listed))
    if spec.credits and spec.credits.description and lines:
        parts.append("Credits\n" + "\n".join(lines))
    return "\n\n".join(parts)
