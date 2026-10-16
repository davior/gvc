"""What a render would cost and whether it can run, worked out without running it.

No network and no ffmpeg: the editor asks on every change to say "about 3 minutes,
1,840 characters of narration" and which placeholders would stop a full render. The
length is a reading-rate guess (Notes' figure: about fifteen characters a second); the
render measures the real thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.render.compile import beat_pause_ms
from app.render.media import used_keys
from app.spec.model import GeneratedAsset, NotesAsset, SearchAsset, VideoSpec

CHARS_PER_SECOND = 15.0


@dataclass
class Estimate:
    seconds: float
    narration_chars: int
    # Unknown clip lengths make `seconds` a floor rather than a guess.
    seconds_is_floor: bool = False
    # What stops a full render, and what stops even a preview.
    blocks_render: List[str] = field(default_factory=list)
    blocks_preview: List[str] = field(default_factory=list)


def estimate(spec: VideoSpec) -> Estimate:
    used = used_keys(spec)
    out = Estimate(seconds=0.0, narration_chars=0)
    for key in sorted(used):
        ref = spec.assets[key]
        if isinstance(ref, NotesAsset):
            message = f"“{ref.label or ref.url}” is still in the note: copy the note's files into GAM."
            out.blocks_render.append(message)
            out.blocks_preview.append(message)
        elif isinstance(ref, SearchAsset) and ref.result is None:
            out.blocks_render.append(f"Footage still to find: “{ref.query}”.")
        elif isinstance(ref, GeneratedAsset) and ref.result is None:
            out.blocks_render.append(f"Still to generate: “{ref.prompt}”.")
    if not spec.segments:
        out.blocks_render.append("There is nothing in this video yet.")
        out.blocks_preview.append("There is nothing in this video yet.")

    for segment in spec.segments:
        speed = (segment.narration.voice.speed if segment.narration and segment.narration.voice
                 and segment.narration.voice.speed else spec.voice.speed)
        beats = segment.beats
        chars = sum(len(b.text) for b in beats if b.speak)
        out.narration_chars += chars
        spoken = chars / CHARS_PER_SECOND / max(0.5, speed)
        spoken += sum(beat_pause_ms(spec, beats, i) for i in range(len(beats))) / 1000.0
        if segment.duration and segment.duration.fixed:
            out.seconds += segment.duration.fixed
        elif segment.kind == "card":
            out.seconds += max(spec.style.cards.seconds, spoken)
        elif segment.kind == "clip":
            trim = segment.visual.trim if segment.visual else None
            if trim and trim.out is not None:
                out.seconds += trim.out - trim.in_
            else:
                out.seconds_is_floor = True
        else:
            floor = (segment.duration.min if segment.duration and segment.duration.min
                     else spec.style.min_segment_seconds)
            out.seconds += max(floor, spoken)
    out.seconds = round(out.seconds, 1)
    return out
