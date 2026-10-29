"""Choosing a model from GAM's catalogue, its options, and what a run will roughly cost.

GAM matches every option against the model's declared values *with its type*: Kling's
duration is the string "5", Veo's is "8s". So choices are always made from the
catalogue's own lists, never constructed.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from app.render.options import frame_size

# A placeholder's type, as the generation kind GAM runs. With base images an image
# becomes an edit of them (image→image); a video is always made from a picture.
KINDS = {"image": "text_to_image", "video": "image_to_video"}

# FLUX names its sizes rather than its ratios; these are the ones for each output aspect,
# and their size in pixels, for the per-megapixel price.
_SIZE_FOR_ASPECT = {"16:9": "landscape_16_9", "9:16": "portrait_16_9", "1:1": "square_hd"}
_SIZE_PIXELS = {
    "square_hd": (1024, 1024), "square": (512, 512), "portrait_4_3": (768, 1024),
    "portrait_16_9": (576, 1024), "landscape_4_3": (1024, 768), "landscape_16_9": (1024, 576),
}

MAX_IMAGE_OUTPUTS = 4

# How much bigger than the video frame a generated picture is asked to be. A picture the
# size of the frame is only sharp while it holds still: a Ken Burns zoom or an S1 frame
# crop reads a part of it and scales that up to the frame. 1.5x leaves room for the
# usual drift and a crop to two thirds before anything is upscaled.
PICTURE_HEADROOM = 1.5

# fal's megapixel, which it bills in whole units of (gam: app/generation/pricing.py).
_FAL_MEGAPIXEL = 1024 * 1024
# A size tier named by its square side in thousands: Nano Banana's "2K", Seedream's
# "auto_4K". "2K" is about 2048² pixels in whatever aspect is asked for.
_TIER = re.compile(r"^(?:auto_)?(\d+(?:\.\d+)?)K$", re.IGNORECASE)

Size = Tuple[int, int]


class CatalogueError(Exception):
    """No model can do what was asked; the message says why."""


def kind_for(asset_type: str, has_base: bool) -> str:
    if asset_type == "image":
        return "image_to_image" if has_base else "text_to_image"
    if asset_type == "video":
        return "image_to_video"
    raise CatalogueError("Only pictures and video can be generated; music and sound "
                         "effects have to come from your library.")


def pick_model(models: List[Dict[str, Any]], kind: str,
               preferred: Optional[str] = None) -> Dict[str, Any]:
    """The model asked for if it can do this kind, else the catalogue's first of the kind
    (GAM lists them in its own preferred order)."""
    of_kind = [m for m in models if m.get("kind") == kind and m.get("is_active", True)]
    if preferred:
        for model in of_kind:
            if model.get("id") == preferred:
                return model
        raise CatalogueError("That model can't do this kind of generation.")
    if not of_kind:
        raise CatalogueError(f"The asset library has no active model for {kind.replace('_', ' ')}.")
    return of_kind[0]


def _seconds(value: Any) -> Optional[float]:
    match = re.search(r"\d+(\.\d+)?", str(value))
    return float(match.group()) if match else None


def target_size(aspect: str, resolution: str) -> Size:
    """The picture to ask for: the frame of this aspect at the video's resolution, with
    headroom. A 1:1 picture in a 1080p video is 1620x1620, since the output's short edge
    is what sets the scale."""
    width, height = frame_size(aspect, resolution)
    return (_even(width * PICTURE_HEADROOM), _even(height * PICTURE_HEADROOM))


def _even(value: float) -> int:
    n = max(2, int(round(value)))
    return n - n % 2


def _custom(limits: Dict[str, Any], target: Size) -> Size:
    """The target, shrunk to fit the model's limits with its aspect kept, and each side
    rounded down to the model's multiple, which GAM would otherwise do itself."""
    width, height = target
    scale = min(1.0, limits["max_width"] / width, limits["max_height"] / height)
    if limits.get("max_pixels"):
        scale = min(scale, math.sqrt(limits["max_pixels"] / (width * height)))
    step = max(1, int(limits.get("multiple_of") or 1))
    return (max(step, int(width * scale) // step * step),
            max(step, int(height * scale) // step * step))


def _tier(values: List[Any], target: Size, floor: Size) -> Optional[Any]:
    """The size tier closest to the target, but never one below the frame itself.

    Closest by ratio rather than the smallest at or above: the tiers are a factor of
    four apart in pixels, so "at least 1.5x" would turn a 1080p video's 2K picture
    (1.43x) into a 4K one (5.7x), slower and dearer. Below the frame is the one thing never
    chosen while a larger tier exists.
    """
    tiers = []
    for value in values:
        match = _TIER.match(str(value))
        if match:
            tiers.append((float(match.group(1)) ** 2 * _FAL_MEGAPIXEL, value))
    if not tiers:
        return None
    tiers.sort(key=lambda tier: tier[0])
    big_enough = [tier for tier in tiers if tier[0] >= floor[0] * floor[1]] or tiers[-1:]
    wanted = target[0] * target[1]
    # Ties go to the larger tier: sharper is the safer side to be wrong on.
    return min(big_enough, key=lambda tier: (abs(math.log(tier[0] / wanted)), -tier[0]))[1]


def default_params(model: Dict[str, Any], *, aspect: str, outputs: int = 1,
                   duration: Optional[str] = None,
                   target: Optional[Size] = None) -> Dict[str, Any]:
    """Options for one run, chosen from the model's own lists.

    `target` is the picture size wanted, from `target_size`. With it, a model that takes
    any size (GAM's `custom_size`) is asked for exactly that, and one with size tiers for
    the nearest that is not smaller than the frame. A GAM older than `custom_size` never
    lists it, so it is asked for tiers or presets as before.
    """
    options = model.get("options") or {}
    params: Dict[str, Any] = {}
    ratios = options.get("aspect_ratios") or []
    sizes = options.get("image_sizes") or []
    custom = options.get("custom_size") if target else None
    if custom:
        # The size carries the aspect; a ratio or preset alongside it would conflict.
        params["width"], params["height"] = _custom(custom, target)
    elif aspect in ratios:
        params["aspect_ratio"] = aspect
    elif _SIZE_FOR_ASPECT.get(aspect) in sizes:
        params["image_size"] = _SIZE_FOR_ASPECT[aspect]
    if target and not custom:
        floor = (round(target[0] / PICTURE_HEADROOM), round(target[1] / PICTURE_HEADROOM))
        resolution = _tier(options.get("resolutions") or [], target, floor)
        if resolution is not None:
            params["resolution"] = resolution
        elif "image_size" not in params:
            auto = _tier(sizes, target, floor)
            if auto is not None:
                params["image_size"] = auto
    durations = options.get("durations") or []
    if durations:
        # A requested duration is matched by its number, so "6" finds Veo's "6s".
        wanted = _seconds(duration) if duration is not None else None
        chosen = next((d for d in durations if wanted is not None and _seconds(d) == wanted),
                      durations[0])
        params["duration"] = chosen
    most = max(1, int(options.get("max_outputs") or 1))
    params["num_outputs"] = max(1, min(outputs, most, MAX_IMAGE_OUTPUTS))
    return params


def estimate(model: Dict[str, Any], params: Dict[str, Any]) -> Optional[float]:
    """The list price of one run, from the catalogue. An estimate, never a bill: GAM
    records what fal actually charged once it has run."""
    price, unit = model.get("unit_price"), model.get("price_unit")
    if price is None or not unit:
        return None
    count = params.get("num_outputs", 1)
    # A per-image price is the catalogue's one figure, for the model's default size.
    # Nano Banana's rises with resolution, so a 2K or 4K run costs more than this says.
    if unit == "image" or unit == "video":
        return round(price * count, 4)
    if unit == "second":
        return round(price * (_seconds(params.get("duration")) or 5.0) * count, 4)
    if unit == "megapixel":
        if params.get("width") and params.get("height"):
            width, height = params["width"], params["height"]
        else:
            width, height = _SIZE_PIXELS.get(params.get("image_size"), (1024, 1024))
        # fal bills each picture in whole megapixels of 1024², rounded up.
        return round(price * math.ceil(width * height / _FAL_MEGAPIXEL) * count, 4)
    return None


def price_line(model: Dict[str, Any]) -> str:
    """The catalogue's price as a person reads it: "$0.07 a second"."""
    price, unit = model.get("unit_price"), model.get("price_unit")
    if price is None or not unit:
        return "price unknown"
    return f"${price:g} a {unit}"
