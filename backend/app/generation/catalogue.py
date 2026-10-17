"""Choosing a model from GAM's catalogue, its options, and what a run will roughly cost.

GAM matches every option against the model's declared values *with its type*: Kling's
duration is the string "5", Veo's is "8s". So choices are always made from the
catalogue's own lists, never constructed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

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


def default_params(model: Dict[str, Any], *, aspect: str, outputs: int = 1,
                   duration: Optional[str] = None) -> Dict[str, Any]:
    """Options for one run, chosen from the model's own lists."""
    options = model.get("options") or {}
    params: Dict[str, Any] = {}
    ratios = options.get("aspect_ratios") or []
    sizes = options.get("image_sizes") or []
    if aspect in ratios:
        params["aspect_ratio"] = aspect
    elif _SIZE_FOR_ASPECT.get(aspect) in sizes:
        params["image_size"] = _SIZE_FOR_ASPECT[aspect]
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
    if unit == "image" or unit == "video":
        return round(price * count, 4)
    if unit == "second":
        return round(price * (_seconds(params.get("duration")) or 5.0) * count, 4)
    if unit == "megapixel":
        width, height = _SIZE_PIXELS.get(params.get("image_size"), (1024, 1024))
        return round(price * width * height / 1_000_000 * count, 4)
    return None


def price_line(model: Dict[str, Any]) -> str:
    """The catalogue's price as a person reads it: "$0.07 a second"."""
    price, unit = model.get("unit_price"), model.get("price_unit")
    if price is None or not unit:
        return "price unknown"
    return f"${price:g} a {unit}"
