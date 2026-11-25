"""Which registry keys a video actually uses."""

from __future__ import annotations

from typing import Any, Dict, Set


def used_asset_keys(data: Dict[str, Any]) -> Set[str]:
    """The registry keys the video draws or plays: a scene's visual, an image overlay, an
    audio track, the background picture, the watermark, and the pictures a used clip is
    made from.

    A key can outlive what used it: the assistant's `generate_image` adds a new key
    rather than filling the scene's placeholder, and placing a library picture replaces
    a scene's visual without removing the old key. The editor's `usedAssetKeys`
    (frontend/src/spec/footage.ts) is the same rule and must stay so: it decides what is
    "still to make", and this decides what the assistant is told is unused and may tidy.
    """
    used: Set[Any] = set()
    style = data.get("style") if isinstance(data.get("style"), dict) else {}
    used.add((style.get("background") or {}).get("asset"))
    chrome = data.get("chrome") if isinstance(data.get("chrome"), dict) else {}
    used.add((chrome.get("watermark") or {}).get("asset"))
    for segment in data.get("segments") or []:
        used.add((segment.get("visual") or {}).get("asset"))
        for overlay in segment.get("overlays") or []:
            if overlay.get("type") == "image":
                used.add(overlay.get("asset"))
    for track in data.get("audio_tracks") or []:
        used.add(track.get("asset"))
    assets = data.get("assets") or {}
    for key in list(used):
        ref = assets.get(key) or {}
        if ref.get("from") == "generate":
            used.update(ref.get("base_assets") or [])
    used.discard(None)
    return used
