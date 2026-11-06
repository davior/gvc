"""A VideoSpec laid out from a GAM playlist: one segment per item, in order.

GAM keeps each playlist item as an asset that owns its file plus an optional range on
it (gam#70, its `docs/playlists.md`), which is exactly a GAM asset ref and a `trim` here,
so nothing is translated, only placed:

- a **video** item is a `clip` segment: the moment plays with its own sound, trimmed to
  the item's range (no trim for a whole video);
- an **image** is a silent `scene` held for the item's seconds, moving with the project's
  Ken Burns default;
- an **audio** item has no picture of its own, so it is a `scene` on the background,
  with a lower third naming it, held for the item's length, and the sound is an audio
  track anchored to that scene's start and end. Anchored, not timed, so moving or
  inserting scenes later keeps the sound with its scene.

A title card from the playlist's name goes first. Each item's label becomes the segment's
label and its chapter mark, so the finished video can be navigated by moment.

Pure: the caller fetches the playlist (as the signed-in user) and stores the result.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.clock import utcnow
from app.schemas_gam import GamPlaylistDetail, GamPlaylistItem
from app.spec.model import VideoSpec

# What an image is held for when GAM did not say (GAM's own default).
IMAGE_SECONDS = 5.0
# An audio item whose length GAM never measured still needs a scene to sit on.
UNKNOWN_AUDIO_SECONDS = 10.0


def _name(item: GamPlaylistItem) -> str:
    return (item.label or item.asset_name or "Untitled").strip()[:200]


def _trim(item: GamPlaylistItem) -> Optional[dict]:
    if item.in_point is None or item.out_point is None:
        return None
    return {"in": item.in_point, "out": item.out_point}


def playlist_spec(playlist: GamPlaylistDetail, title: str = "") -> VideoSpec:
    title = (title or playlist.name or "Untitled video").strip()
    assets: Dict[str, dict] = {}
    keys: Dict[str, str] = {}
    segments: List[dict] = [{
        "id": "s_title", "kind": "card", "role": "title", "label": "Title",
        "card": {"variant": "title", "title": title,
                 **({"subtitle": playlist.description} if playlist.description else {})},
    }]
    tracks: List[dict] = []

    def key_for(item: GamPlaylistItem) -> str:
        # One asset entry per GAM asset, however many of its moments are used.
        if item.asset_id not in keys:
            keys[item.asset_id] = f"g{len(keys) + 1}"
            assets[keys[item.asset_id]] = {
                "from": "gam", "id": item.asset_id, "type": item.asset_type,
                "label": item.asset_name or None,
            }
        return keys[item.asset_id]

    for number, item in enumerate(playlist.items, start=1):
        if item.asset_type not in ("video", "image", "audio"):
            continue
        key, name, segment_id = key_for(item), _name(item), f"s_{number}"
        base = {"id": segment_id, "label": name, "chapter": name}
        if item.asset_type == "video":
            visual = {"asset": key, "audio": "play", "loop": False}
            if _trim(item):
                visual["trim"] = _trim(item)
            segments.append({**base, "kind": "clip", "visual": visual})
        elif item.asset_type == "image":
            seconds = item.end or item.image_seconds or IMAGE_SECONDS
            segments.append({**base, "kind": "scene", "visual": {"asset": key},
                             "duration": {"fixed": seconds}})
        else:
            length = (item.end - item.start) if item.end is not None else None
            seconds = length if length and length > 0 else UNKNOWN_AUDIO_SECONDS
            segments.append({
                **base, "kind": "scene", "duration": {"fixed": round(seconds, 3)},
                "overlays": [{"id": "o_name", "type": "lower_third", "title": name}],
            })
            track = {
                "id": f"t_{number}", "kind": "voiceover", "asset": key,
                "start": {"segment": segment_id, "edge": "start"},
                "end": {"segment": segment_id, "edge": "end"},
                "loop": False, "volume": 1.0, "duck_under_narration": False,
            }
            if _trim(item):
                track["trim"] = _trim(item)
            tracks.append(track)

    return VideoSpec.model_validate({
        "title": title,
        "source": {"kind": "playlist", "playlist_id": playlist.id, "name": playlist.name,
                   "imported_at": utcnow().isoformat(timespec="seconds") + "Z"},
        "style": {
            # As a project made by hand starts (spec/starter.py).
            "transition": {"style": "fade", "duration": 0.6},
            "motion": {"effect": "alternate", "amount": 0.12},
        },
        "assets": assets,
        "segments": segments,
        "audio_tracks": tracks,
    })
