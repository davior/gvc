"""The files a render needs, made local.

GVC owns no media: everything a video shows or plays lives in GAM. A render streams
each file it needs into a cache once, keyed on GAM's id and checked against GAM's
size, so rendering the same project again (a preview, then the full render) fetches
nothing twice. Signed URLs are asked for at render time, because they expire.

What cannot be fetched is said per asset, all at once, before anything is encoded:
- a placeholder still to find or generate is drawn as a slate in a preview, and
  refuses a full render;
- a file still inside the note a project was pushed from refuses both, with the fix.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set

from PIL import Image

from app.config import settings
from app.gam.client import GamClient
from app.schemas_gam import GamAssetRead, GamVersion
from app.render import compose
from app.render import ffmpeg as F
from app.render.compile import Media
from app.spec.model import (
    GamAsset, GeneratedAsset, ImageOverlay, NotesAsset, SearchAsset, VideoSpec,
)

logger = logging.getLogger(__name__)


@dataclass
class Resolution:
    media: Dict[str, Media] = field(default_factory=dict)
    # Reasons the render cannot go ahead, one per asset.
    problems: List[str] = field(default_factory=list)
    # Each GAM asset's credit line as GAM resolves it (a clip's inherited from its
    # parent), for the end credits. Empty for an asset nobody has attributed.
    credits: Dict[str, str] = field(default_factory=dict)


def keys_in_order(spec: VideoSpec) -> List[str]:
    """The asset keys the video shows or plays, in the order a viewer meets them:
    scene by scene (its picture, then its overlays), then the soundtrack."""
    ordered: List[str] = []
    for segment in spec.segments:
        if segment.visual is not None:
            ordered.append(segment.visual.asset)
        ordered += [o.asset for o in segment.overlays if isinstance(o, ImageOverlay)]
    ordered += [t.asset for t in spec.audio_tracks]
    return list(dict.fromkeys(k for k in ordered if k in spec.assets))


def used_keys(spec: VideoSpec) -> Set[str]:
    """Every asset key the render will read."""
    keys = set(keys_in_order(spec))
    if spec.style.background.type == "image" and spec.style.background.asset:
        keys.add(spec.style.background.asset)
    if spec.chrome.watermark and spec.chrome.watermark.asset:
        keys.add(spec.chrome.watermark.asset)
    return keys


def fills_frame(spec: VideoSpec, key: str) -> bool:
    """Whether any shot shows this asset cropped to fill the frame.

    That is the shot that needs the most pixels: `crop` scales the picture until it
    covers the whole frame, so a 16:9 video in a 9:16 frame is shown at its height,
    while `blur` and `pad` only have to fit it inside.
    """
    return any(
        (segment.visual.fit or spec.style.fit) == "crop"
        for segment in spec.segments
        if segment.visual is not None and segment.visual.asset == key
    )


class SourceFile(NamedTuple):
    # The render cache's key: GAM's file id, plus the size for a version, so a 720p
    # and the original of one video are cached side by side.
    cache_id: str
    url: str
    size_bytes: int
    width: Optional[int]
    height: Optional[int]
    # None for the original.
    short_side: Optional[int] = None


# Rounding to even dimensions can leave a version a pixel or two short of a frame it
# was made for (a 1002x750 original's 1080p is 1442x1080), which should still count.
_SLACK_PX = 2


def pick_source(
    asset: GamAssetRead, file_id: str, versions: List[GamVersion], frame: tuple, *, fill: bool
) -> SourceFile:
    """The best match among a video's original and its versions for this frame.

    The smallest file that is still at least as sharp as the frame shows it: a 1080p
    render of a 4K original reads its 1080p version, a quarter of the bytes to fetch
    and decode for the same picture, and a preview reads its 480p. When no file is big
    enough the biggest one is used, which is the original. A file whose size GAM does
    not know is never chosen over one it does.
    """
    frame_w, frame_h = frame
    original = SourceFile(file_id, asset.file_url or "", asset.size_bytes, asset.width, asset.height)
    candidates = [original] + [
        SourceFile(f"{file_id}@{v.short_side}", v.file_url, v.size_bytes, v.width, v.height,
                   v.short_side)
        for v in versions
        if v.file_url and v.width and v.height
    ]
    if len(candidates) == 1 or not (asset.width and asset.height):
        return original

    def sharp_enough(c: SourceFile) -> bool:
        wide = c.width + _SLACK_PX >= frame_w
        tall = c.height + _SLACK_PX >= frame_h
        # Covering the frame needs both; fitting inside it needs whichever edge the
        # frame's shape makes the limit, which is the same as either reaching it.
        return (wide and tall) if fill else (wide or tall)

    def pixels(c: SourceFile) -> int:
        return (c.width or 0) * (c.height or 0)

    enough = [c for c in candidates if sharp_enough(c)]
    return min(enough, key=pixels) if enough else max(candidates, key=pixels)


def _probe(path: str, kind: str) -> Media:
    if kind == "image":
        try:
            with Image.open(path) as image:
                width, height = image.size
        except OSError:
            width = height = None
        return Media(path=path, kind="image", width=width, height=height)
    return Media(path=path, kind=kind, duration=F.probe_duration(path) or None,
                 has_audio=F.probe_has_audio(path) if kind == "video" else True)


def _slate(work_dir: str, key: str, title: str, subtitle: str, width: int, height: int) -> Media:
    """A placeholder drawn as a card, so a preview shows where it will go."""
    path = os.path.join(work_dir, f"slate_{key}.png")
    compose.card_image(width, height, title=title, subtitle=subtitle).convert("RGB").save(path, "PNG")
    return Media(path=path, kind="slate", width=width, height=height)


class MediaCache:
    """GAM files on local disk, pruned oldest-used first past the size cap."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def fetch(self, gam: GamClient, file_id: str, file_url: str, size: int) -> str:
        path = self.root / file_id
        meta = self.root / f"{file_id}.json"
        if path.exists() and meta.exists():
            try:
                if json.loads(meta.read_text()).get("size") == size and size:
                    os.utime(path)  # recently used: last to be pruned
                    return str(path)
            except ValueError:
                pass
        # Streamed to a temporary name and renamed, so a render interrupted
        # mid-download never leaves a truncated file that looks complete.
        handle, tmp = tempfile.mkstemp(dir=self.root, prefix=".part-")
        try:
            with os.fdopen(handle, "wb") as sink:
                written = gam.download(file_url, sink,
                                       max_bytes=settings.render_max_file_mb * 1024 * 1024)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        meta.write_text(json.dumps({"size": size or written}))
        return str(path)

    def prune(self, max_bytes: int) -> None:
        files = [p for p in self.root.iterdir() if p.is_file() and not p.name.endswith(".json")
                 and not p.name.startswith(".part-")]
        files.sort(key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= max_bytes:
                break
            total -= path.stat().st_size
            for doomed in (path, path.with_name(path.name + ".json")):
                try:
                    doomed.unlink()
                except OSError:
                    pass


def resolve(
    spec: VideoSpec, gam: GamClient, *, cache: MediaCache, work_dir: str, preview: bool,
    frame: tuple,
) -> Resolution:
    out = Resolution()
    width, height = frame
    for key in sorted(used_keys(spec)):
        ref = spec.assets[key]
        if isinstance(ref, NotesAsset):
            out.problems.append(f"“{ref.label or ref.url}” is still inside the note this came "
                                "from. Copy the note's files into GAM first.")
            continue
        if isinstance(ref, SearchAsset) and ref.result is None:
            if preview:
                out.media[key] = _slate(work_dir, key, "To find", ref.query, width, height)
            else:
                out.problems.append(f"Footage still to find: “{ref.query}”.")
            continue
        if isinstance(ref, GeneratedAsset) and ref.result is None:
            if preview:
                out.media[key] = _slate(work_dir, key, "To generate", ref.prompt, width, height)
            else:
                out.problems.append(f"Still to generate: “{ref.prompt}”.")
            continue

        gam_id = ref.result.id if isinstance(ref, (SearchAsset, GeneratedAsset)) else ref.id
        label = ref.label or gam_id
        # GamError (the library unreachable) propagates: that is one problem for the
        # whole render, not one per asset.
        asset = gam.get_asset(gam_id)
        if asset is None:
            out.problems.append(f"“{label}” is no longer in the asset library.")
            continue
        if asset.missing or not asset.file_url:
            out.problems.append(f"“{asset.name}” has no file in the asset library.")
            continue
        # A GAM clip plays its parent's bytes, so the parent's file is what is cached.
        file_id = asset.parent_asset_id if asset.parent_asset_id and asset.in_point is not None \
            else asset.id
        kind = asset.asset_type if asset.asset_type in ("image", "video", "audio") else "video"
        source = SourceFile(file_id, asset.file_url, asset.size_bytes, asset.width, asset.height)
        if kind == "video":
            # A clip's versions are its parent's: the same file at other sizes, over
            # the same timeline, so its in and out points still hold.
            source = pick_source(asset, file_id, gam.versions(file_id), frame,
                                 fill=fills_frame(spec, key))
            if source.short_side is not None:
                logger.info("Rendering “%s” from its %sp version", asset.name, source.short_side)
        path = cache.fetch(gam, source.cache_id, source.url, source.size_bytes)
        media = _probe(path, kind)
        if file_id != asset.id:
            media.offset = asset.in_point or 0.0
            if asset.out_point is not None:
                media.length = max(0.1, asset.out_point - (asset.in_point or 0.0))
        out.media[key] = media
        out.credits[key] = asset.credit or ""

    try:
        cache.prune(int(settings.render_cache_max_gb * 1024 ** 3))
    except OSError:
        logger.exception("Could not prune the render media cache")
    return out
