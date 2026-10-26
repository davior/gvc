"""The assistant's operations on a video: the Notes spec doc's §8.2, addressed by id.

Every edit works on a `Working` copy of the spec, never on the project. Nothing reaches
the project until a person applies the proposal the turn ends with.

Each edit is checked with `parse_spec` the moment it is made, and the issues go straight
back to the model as the tool's result, so a mistake is fixed in the same turn by the
same model that made it. That is the plan of attack's "one repair round" (D2),
generalised to every edit rather than only a first draft.

Two rules decide what an edit that produces issues does:
- **A valid spec stays valid.** An edit that would break it is refused, and the spec is
  left as it was, so a slip can't wreck a working video.
- **An invalid spec can be repaired step by step.** After `replace_spec` with mistakes
  in it, each edit is accepted while issues remain, and the result says which are left.

Items are addressed by their ids, never by list position. JSON Patch indexes (the Notes
spec doc, open decision 14) point at the wrong item as soon as something is reordered.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.gam.client import GamClient, GamError
from app.providers.base import ToolCall, ToolResult, ToolSpec
from app.render.estimate import estimate
from app.services import note_media as note_files
from app.spec.validation import SpecIssue, parse_spec

# A found moment is padded so a cut doesn't clip a word: the editor's `momentTrim`.
MOMENT_PAD = 0.5
DEFAULT_MOMENT_SECONDS = 5.0
MAX_SEARCH_HITS = 12
MAX_NOTE_IMPORT = 40


class ToolFailed(Exception):
    """The call can't be done as asked; the message goes back to the model."""


def _issues_text(issues: List[SpecIssue], limit: int = 20) -> str:
    lines = [f"- {'.'.join(str(p) for p in i.path) or '(spec)'}: {i.message}"
             for i in issues[:limit]]
    if len(issues) > limit:
        lines.append(f"- … and {len(issues) - limit} more")
    return "\n".join(lines)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:32]


def merge(base: Any, changes: Any) -> Any:
    """A JSON merge patch (RFC 7386): objects merge, a null removes, anything else
    replaces. Lists are replaced whole, which is what "these are the beats" means."""
    if not isinstance(changes, dict) or not isinstance(base, dict):
        return copy.deepcopy(changes)
    out = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = merge(out.get(key), value)
    return out


@dataclass
class Hit:
    """What a search found, kept so `set_visual` can take its moment as the trim."""

    gam_id: str
    name: str
    asset_type: str
    duration: Optional[float]
    start: Optional[float]
    end: Optional[float]


@dataclass
class Working:
    data: Dict[str, Any]
    gam: Optional[GamClient] = None
    changes: List[str] = field(default_factory=list)
    hits: Dict[str, Hit] = field(default_factory=dict)
    issues: List[SpecIssue] = field(default_factory=list)
    # Starts one image generation in GAM for a placeholder in `data` and says what it
    # cost: (model label, estimated cost). Set by the worker; None in a turn that can't
    # generate (no GAM), and then the tool says so.
    generate: Optional[Callable[[Dict[str, Any], str, str, List[str], int],
                                Tuple[str, Optional[float]]]] = None
    max_generations: int = 6
    generated: int = 0
    # The files of the attached notes by the id the assistant sees (attachments.media_ids),
    # and what each became in the library once imported, so asking twice copies once.
    note_media: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    imported: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data = copy.deepcopy(self.data)
        _, self.issues = parse_spec(self.data)

    @property
    def valid(self) -> bool:
        return not self.issues

    # ── lookups ──────────────────────────────────────────────────────────────

    def segments(self) -> List[Dict[str, Any]]:
        return self.data.setdefault("segments", [])

    def segment(self, segment_id: str) -> Dict[str, Any]:
        for segment in self.segments():
            if segment.get("id") == segment_id:
                return segment
        known = ", ".join(s.get("id", "?") for s in self.segments()) or "none"
        raise ToolFailed(f"No segment {segment_id!r}. The segments are: {known}.")

    def index_of(self, segment_id: str) -> int:
        return self.segments().index(self.segment(segment_id))

    def name_of(self, segment: Dict[str, Any]) -> str:
        return segment.get("label") or segment.get("id", "?")

    def tracks(self) -> List[Dict[str, Any]]:
        return self.data.setdefault("audio_tracks", [])

    def track(self, track_id: str) -> Dict[str, Any]:
        for track in self.tracks():
            if track.get("id") == track_id:
                return track
        raise ToolFailed(f"No audio track {track_id!r}.")

    def new_id(self, prefix: str, taken: List[str]) -> str:
        n = len(taken) + 1
        while f"{prefix}{n}" in taken:
            n += 1
        return f"{prefix}{n}"

    def all_overlay_ids(self) -> List[str]:
        return [o.get("id") for s in self.segments() for o in s.get("overlays", [])]

    def register_gam(self, data: Dict[str, Any], gam_id: str, *,
                     asset_type: Optional[str] = None, label: Optional[str] = None) -> str:
        """The asset key for a GAM asset in `data`, added to its registry if new.

        `data` rather than `self.data`: edits build a candidate and commit it whole, so
        a refused edit leaves no stray registry entry behind.
        """
        assets = data.setdefault("assets", {})
        for key, ref in assets.items():
            if ref.get("from") == "gam" and ref.get("id") == gam_id:
                return key
        hit = self.hits.get(gam_id)
        label = label or (hit.name if hit else None)
        asset_type = asset_type or (hit.asset_type if hit else None)
        base = f"a_{_slug(label or '') or 'gam'}"
        key, n = base, 2
        while key in assets:
            key, n = f"{base}_{n}", n + 1
        ref: Dict[str, Any] = {"from": "gam", "id": gam_id}
        if asset_type in ("image", "video", "audio"):
            ref["type"] = asset_type
        if label:
            ref["label"] = label
        assets[key] = ref
        return key

    # ── committing ───────────────────────────────────────────────────────────

    def commit(self, candidate: Dict[str, Any], summary: str) -> str:
        """Take `candidate` as the new spec if the rules above allow it."""
        _, issues = parse_spec(candidate)
        if issues and self.valid:
            raise ToolFailed("That edit would make the video invalid, so it was not made:\n"
                             + _issues_text(issues))
        self.data, self.issues = candidate, issues
        self.changes.append(summary)
        if issues:
            return (f"Done: {summary}. The video still has issues to fix:\n"
                    + _issues_text(issues))
        return f"Done: {summary}."


# ── the tools ─────────────────────────────────────────────────────────────────

def _compact(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def get_spec(w: Working, segment_id: Optional[str] = None) -> str:
    if segment_id:
        return _compact(w.segment(segment_id))
    return _compact(w.data)


def _music_row(music) -> Dict[str, Any]:
    """A track's profile with the empty parts left out, so a hit costs no more tokens
    than what is actually known about it. Vocals are spelled as the word that matters
    when choosing music under narration, and left out entirely when not known: a missing
    key is what tells the model it cannot assume either way."""
    row: Dict[str, Any] = {}
    for name in ("genres", "moods", "instruments"):
        terms = getattr(music, name)
        if terms:
            row[name] = terms
    if music.bpm is not None:
        row["bpm"] = round(music.bpm)
    if music.key:
        row["key"] = music.key
    if music.energy:
        row["energy"] = music.energy
    if music.vocals is not None:
        row["vocals"] = "yes" if music.vocals else "instrumental"
    return row


def search_assets(w: Working, query: str, type: Optional[str] = None,
                  limit: int = 8) -> str:
    if w.gam is None:
        raise ToolFailed("The asset library isn't reachable in this turn.")
    try:
        found = w.gam.search(query, asset_type=type, limit=max(1, min(MAX_SEARCH_HITS, limit)))
    except GamError as exc:
        raise ToolFailed(f"The asset library search failed: {exc.message}")
    rows = []
    for hit in found.data:
        asset = hit.asset
        w.hits[asset.id] = Hit(asset.id, asset.name, asset.asset_type, asset.duration_seconds,
                               hit.start_time, hit.end_time)
        row: Dict[str, Any] = {"gam_id": asset.id, "name": asset.name, "type": asset.asset_type}
        if asset.duration_seconds:
            row["duration"] = round(asset.duration_seconds, 1)
        if hit.start_time is not None:
            # Where in the video it was said: what `set_visual` will cut to.
            row["said_at"] = [round(hit.start_time, 1),
                              round(hit.end_time, 1) if hit.end_time is not None else None]
        if hit.snippet:
            row["snippet"] = hit.snippet.replace("«", "").replace("»", "")[:240]
        if asset.credit:
            row["credit"] = asset.credit
        if asset.width and asset.height:
            row["size"] = f"{asset.width}x{asset.height}"
        if asset.audio_kind:
            row["kind"] = asset.audio_kind
        if asset.music:
            row["music"] = _music_row(asset.music)
        rows.append(row)
    if not rows:
        return (f"Nothing in the library matches {query!r}. Try other words, or leave a "
                "placeholder with add_placeholder.")
    return _compact({"query": query, "semantic": found.semantic, "hits": rows})


def get_asset(w: Working, gam_id: str) -> str:
    if w.gam is None:
        raise ToolFailed("The asset library isn't reachable in this turn.")
    try:
        asset = w.gam.get_asset(gam_id)
    except GamError as exc:
        raise ToolFailed(f"The asset library failed: {exc.message}")
    if asset is None:
        raise ToolFailed(f"No asset {gam_id!r} in the library.")
    details = {"gam_id": asset.id, "name": asset.name, "type": asset.asset_type,
               "duration": asset.duration_seconds, "width": asset.width,
               "height": asset.height, "credit": asset.credit,
               "clip_of": asset.parent_asset_id}
    if asset.audio_kind:
        details["kind"] = asset.audio_kind
    if asset.music:
        details["music"] = _music_row(asset.music)
    return _compact(details)


def replace_spec(w: Working, spec: Dict[str, Any]) -> str:
    if not isinstance(spec, dict):
        raise ToolFailed("spec must be a VideoSpec object.")
    candidate = copy.deepcopy(spec)
    # The project owns its id; a draft never changes it.
    if "id" in w.data:
        candidate["id"] = w.data["id"]
    # Accepted even with issues: a whole draft is the one edit too big to throw away
    # over a typo. The issues come back to be fixed with the other tools.
    _, issues = parse_spec(candidate)
    w.data, w.issues = candidate, issues
    w.changes.append(f"Drafted the video: {len(candidate.get('segments', []))} segments")
    if issues:
        return (f"The draft is in place, with {len(issues)} issue"
                f"{'s' if len(issues) != 1 else ''} to fix:\n" + _issues_text(issues))
    return "Done: the draft is in place and valid."


def import_note_media(w: Working, media_ids: List[str]) -> str:
    """Copy files out of an attached note into the user's library, and register them."""
    if w.gam is None:
        raise ToolFailed("The asset library isn't reachable in this turn.")
    if not w.note_media:
        raise ToolFailed("No note with pictures or videos is attached.")
    if not media_ids or len(media_ids) > MAX_NOTE_IMPORT:
        raise ToolFailed(f"Give between 1 and {MAX_NOTE_IMPORT} ids from the note's file list.")
    unknown = [m for m in media_ids if m not in w.note_media]
    if unknown:
        raise ToolFailed(f"No such note file: {', '.join(unknown)}. The ids are: "
                         f"{', '.join(w.note_media)}.")

    candidate = copy.deepcopy(w.data)
    rows: List[Dict[str, Any]] = []
    failed: List[str] = []
    for media_id in dict.fromkeys(media_ids):
        media = w.note_media[media_id]
        gam_id = w.imported.get(media_id)
        try:
            if gam_id is None:
                stored = note_files.copy_file(media["path"], media_id, w.gam)
                gam_id = w.imported[media_id] = stored.id
                w.hits[gam_id] = Hit(gam_id, stored.name, media["type"],
                                     stored.duration_seconds, None, None)
        except (note_files.CopyFailed, GamError) as exc:
            failed.append(f"{media_id} ({media['name']}): {getattr(exc, 'message', None) or exc}")
            continue
        key = w.register_gam(candidate, gam_id, asset_type=media["type"],
                             label=media["caption"] or media["name"])
        rows.append({"id": media_id, "asset": key, "gam_id": gam_id, "type": media["type"]})
    if not rows:
        raise ToolFailed("Nothing could be copied:\n- " + "\n- ".join(failed))
    summary = f"Brought {len(rows)} file{'s' if len(rows) != 1 else ''} from the note into the library"
    result = w.commit(candidate, summary)
    return (result + " Use set_visual (asset = the key) or add_overlay to put them on scenes."
            + _compact({"imported": rows})
            + ("\nCould not copy:\n- " + "\n- ".join(failed) if failed else ""))


def _insert_at(w: Working, after: Optional[str]) -> int:
    if after in (None, ""):
        return len(w.segments())
    if after == "start":
        return 0
    return w.index_of(after) + 1


def add_segment(w: Working, segment: Dict[str, Any], after: Optional[str] = None) -> str:
    if not isinstance(segment, dict):
        raise ToolFailed("segment must be an object.")
    candidate = copy.deepcopy(w.data)
    taken = [s.get("id") for s in candidate.get("segments", [])]
    segment = copy.deepcopy(segment)
    if not segment.get("id") or segment["id"] in taken:
        segment["id"] = w.new_id("s_", taken)
    position = _insert_at(w, after)
    candidate.setdefault("segments", []).insert(position, segment)
    return w.commit(candidate, f"Added {segment.get('kind', 'segment')} "
                               f"{segment.get('label') or segment['id']} (id {segment['id']})")


def update_segment(w: Working, segment_id: str, changes: Dict[str, Any]) -> str:
    if not isinstance(changes, dict):
        raise ToolFailed("changes must be an object.")
    if "id" in changes:
        raise ToolFailed("A segment's id can't be changed; anchors point at it.")
    candidate = copy.deepcopy(w.data)
    index = w.index_of(segment_id)
    candidate["segments"][index] = merge(candidate["segments"][index], changes)
    fields = ", ".join(sorted(changes)) or "nothing"
    return w.commit(candidate, f"Changed {w.name_of(candidate['segments'][index])}: {fields}")


def move_segment(w: Working, segment_id: str, after: str) -> str:
    candidate = copy.deepcopy(w.data)
    index = w.index_of(segment_id)
    moving = candidate["segments"].pop(index)
    if after == segment_id:
        raise ToolFailed("A segment can't be moved after itself.")
    if after == "start":
        position = 0
    else:
        ids = [s.get("id") for s in candidate["segments"]]
        if after not in ids:
            raise ToolFailed(f"No segment {after!r} to move it after.")
        position = ids.index(after) + 1
    candidate["segments"].insert(position, moving)
    where = "to the start" if after == "start" else f"after {after}"
    return w.commit(candidate, f"Moved {w.name_of(moving)} {where}")


def _anchors_naming(data: Dict[str, Any], segment_id: str) -> List[str]:
    """What points at a segment, so removing it can say what will be orphaned."""
    named = []

    def hits(anchor: Any) -> bool:
        return isinstance(anchor, dict) and anchor.get("segment") == segment_id

    for track in data.get("audio_tracks", []):
        if hits(track.get("start")) or hits(track.get("end")):
            named.append(f"audio track {track.get('id')}")
    for segment in data.get("segments", []):
        for overlay in segment.get("overlays", []):
            show = overlay.get("show") or {}
            if hits(show.get("from")) or hits(show.get("to")):
                named.append(f"overlay {overlay.get('id')} on {segment.get('id')}")
    return named


def remove_segment(w: Working, segment_id: str) -> str:
    candidate = copy.deepcopy(w.data)
    index = w.index_of(segment_id)
    removed = candidate["segments"].pop(index)
    result = w.commit(candidate, f"Removed {w.name_of(removed)}")
    orphans = _anchors_naming(candidate, segment_id)
    if orphans:
        # Allowed, as in the editor: the renderer drops what can't be placed with a
        # warning. Said so the model can re-anchor them.
        result += (" These are still anchored to it and will be left out of the render "
                   "unless re-anchored: " + ", ".join(orphans) + ".")
    return result


def _moment_trim(hit: Hit) -> Optional[Dict[str, float]]:
    if hit.start is None:
        return None
    end = hit.end if hit.end is not None else hit.start + DEFAULT_MOMENT_SECONDS
    a = max(0.0, hit.start - MOMENT_PAD)
    b = end + MOMENT_PAD
    if hit.duration:
        b = min(b, hit.duration)
    return {"in": round(a, 1), "out": round(b, 1)} if b > a else None


def set_visual(w: Working, segment_id: str, gam_id: Optional[str] = None,
               asset: Optional[str] = None, trim: Optional[Dict[str, Any]] = None,
               motion: Optional[Dict[str, Any]] = None, fit: Optional[str] = None,
               audio: Optional[str] = None, loop: Optional[bool] = None) -> str:
    if not gam_id and not asset:
        raise ToolFailed("Give gam_id (from search_assets) or asset (a key in the registry).")
    candidate = copy.deepcopy(w.data)
    if gam_id:
        key = w.register_gam(candidate, gam_id)
    else:
        if asset not in w.data.get("assets", {}):
            raise ToolFailed(f"No asset {asset!r} in the registry.")
        key = asset
    index = w.index_of(segment_id)
    segment = candidate["segments"][index]
    visual: Dict[str, Any] = {"asset": key}
    previous = segment.get("visual") or {}
    if previous.get("asset") == key:
        visual = copy.deepcopy(previous)
    hit = w.hits.get(gam_id) if gam_id else None
    if trim is not None:
        visual["trim"] = trim
    elif hit and hit.asset_type == "video" and _moment_trim(hit):
        # The moment that was said becomes the cut, as picking a hit does in the editor.
        visual["trim"] = _moment_trim(hit)
    if motion is not None:
        visual["motion"] = motion
    if fit is not None:
        visual["fit"] = fit
    if audio is not None:
        visual["audio"] = audio
    if loop is not None:
        visual["loop"] = loop
    segment["visual"] = visual
    label = hit.name if hit else key
    trimmed = f", {visual['trim'].get('in')}–{visual['trim'].get('out')} s" if visual.get("trim") else ""
    return w.commit(candidate, f"{w.name_of(segment)} shows {label}{trimmed}")


def add_placeholder(w: Working, segment_id: str, kind: str, text: str,
                    media_type: str = "video", moment_min: Optional[float] = None,
                    moment_max: Optional[float] = None, use_as: str = "visual") -> str:
    """Footage still to find, or a picture still to generate: drawn as a slate in a
    preview, filled in by a person later."""
    candidate = copy.deepcopy(w.data)
    assets = candidate.setdefault("assets", {})
    base = f"a_{_slug(text) or kind}"
    key, n = base, 2
    while key in assets:
        key, n = f"{base}_{n}", n + 1
    if kind == "search":
        ref: Dict[str, Any] = {"from": "search", "query": text, "type": media_type}
        if media_type == "video" and (moment_min or moment_max):
            ref["moment"] = {k: v for k, v in (("min", moment_min), ("max", moment_max)) if v}
    elif kind == "generate":
        if media_type not in ("image", "video", "music", "sfx"):
            media_type = "image"
        ref = {"from": "generate", "type": media_type, "prompt": text}
    else:
        raise ToolFailed('kind must be "search" or "generate".')
    assets[key] = ref
    index = w.index_of(segment_id)
    segment = candidate["segments"][index]
    if use_as == "visual":
        segment["visual"] = {"asset": key}
    return w.commit(candidate, f"{w.name_of(segment)}: placeholder to "
                               f"{'find' if kind == 'search' else 'generate'}: {text!r}")


def generate_image(w: Working, prompt: str, segment_id: Optional[str] = None,
                   use_as: str = "visual", base_gam_ids: Optional[List[str]] = None,
                   outputs: int = 1, label: Optional[str] = None) -> str:
    """A picture made for the video, started now in GAM and filled in when it's done.

    Images only. Video costs far more and takes minutes, so the user starts that
    themselves from the placeholder (their call, recorded in the plan of attack).
    """
    if w.generate is None:
        raise ToolFailed("Generating isn't available in this turn.")
    if w.generated >= w.max_generations:
        raise ToolFailed(f"That's the {w.max_generations} pictures this request may generate. "
                         "Leave the rest as placeholders with add_placeholder; the user can "
                         "generate them from the video.")
    if not prompt or not prompt.strip():
        raise ToolFailed("Describe the picture to generate.")
    if use_as not in ("visual", "overlay", "none"):
        raise ToolFailed('use_as is "visual", "overlay" or "none".')
    if use_as != "none" and not segment_id:
        raise ToolFailed("Say which segment the picture is for, or use_as \"none\".")
    candidate = copy.deepcopy(w.data)
    assets = candidate.setdefault("assets", {})
    base = f"a_{_slug(label or prompt) or 'generated'}"
    key, n = base, 2
    while key in assets:
        key, n = f"{base}_{n}", n + 1
    ref: Dict[str, Any] = {"from": "generate", "type": "image", "prompt": prompt.strip()}
    if label:
        ref["label"] = label
    assets[key] = ref
    where = "kept in the registry"
    if segment_id:
        segment = candidate["segments"][w.index_of(segment_id)]
        if use_as == "visual":
            segment["visual"] = {"asset": key}
            where = f"as the picture of {w.name_of(segment)}"
        elif use_as == "overlay":
            taken = w.all_overlay_ids()
            segment.setdefault("overlays", []).append(
                {"id": w.new_id("o_", taken), "type": "image", "asset": key,
                 "position": "top-right", "scale_pct": 30})
            where = f"on screen over {w.name_of(segment)}"
    result = w.commit(candidate, f"Generating a picture {where}: {prompt.strip()[:80]!r}")
    try:
        model, cost = w.generate(w.data, key, prompt.strip(), list(base_gam_ids or []),
                                 max(1, min(4, outputs)))
    except Exception as exc:  # noqa: BLE001 - said to the model; the placeholder stays
        return (f"{result} But the generation couldn't start ({exc}); the placeholder "
                f"{key} is there for the user to generate later.")
    w.generated += 1
    price = f", about ${cost:.3f}" if cost is not None else ""
    return (f"{result} Started with {model}{price}; it fills placeholder {key} by itself "
            "in a few seconds.")


def add_overlay(w: Working, segment_id: str, overlay: Dict[str, Any],
                gam_id: Optional[str] = None) -> str:
    if not isinstance(overlay, dict):
        raise ToolFailed("overlay must be an object.")
    candidate = copy.deepcopy(w.data)
    overlay = copy.deepcopy(overlay)
    if gam_id:
        overlay["asset"] = w.register_gam(candidate, gam_id, asset_type="image")
    taken = w.all_overlay_ids()
    if not overlay.get("id") or overlay["id"] in taken:
        overlay["id"] = w.new_id("o_", taken)
    index = w.index_of(segment_id)
    segment = candidate["segments"][index]
    segment.setdefault("overlays", []).append(overlay)
    what = overlay.get("title") or overlay.get("text") or overlay.get("type")
    return w.commit(candidate, f"On {w.name_of(segment)}: added "
                                      f"{overlay.get('type', 'overlay')} {what!r} (id {overlay['id']})")


def _overlay_index(segment: Dict[str, Any], overlay_id: str) -> int:
    for i, overlay in enumerate(segment.get("overlays", [])):
        if overlay.get("id") == overlay_id:
            return i
    raise ToolFailed(f"No overlay {overlay_id!r} on {segment.get('id')}.")


def update_overlay(w: Working, segment_id: str, overlay_id: str, changes: Dict[str, Any]) -> str:
    candidate = copy.deepcopy(w.data)
    segment = candidate["segments"][w.index_of(segment_id)]
    i = _overlay_index(segment, overlay_id)
    segment["overlays"][i] = merge(segment["overlays"][i], changes)
    return w.commit(candidate, f"On {w.name_of(segment)}: changed overlay {overlay_id} "
                               f"({', '.join(sorted(changes))})")


def remove_overlay(w: Working, segment_id: str, overlay_id: str) -> str:
    candidate = copy.deepcopy(w.data)
    segment = candidate["segments"][w.index_of(segment_id)]
    segment["overlays"].pop(_overlay_index(segment, overlay_id))
    return w.commit(candidate, f"On {w.name_of(segment)}: removed overlay {overlay_id}")


def add_audio_track(w: Working, track: Dict[str, Any], gam_id: Optional[str] = None) -> str:
    if not isinstance(track, dict):
        raise ToolFailed("track must be an object.")
    candidate = copy.deepcopy(w.data)
    track = copy.deepcopy(track)
    if gam_id:
        track["asset"] = w.register_gam(candidate, gam_id, asset_type="audio")
    taken = [t.get("id") for t in candidate.get("audio_tracks", [])]
    if not track.get("id") or track["id"] in taken:
        track["id"] = w.new_id("m_" if track.get("kind", "music") == "music" else "x_", taken)
    candidate.setdefault("audio_tracks", []).append(track)
    hit = w.hits.get(gam_id) if gam_id else None
    return w.commit(candidate, f"Added {track.get('kind', 'music')} track "
                                      f"{(hit.name if hit else track.get('asset'))!r} (id {track['id']})")


def update_audio_track(w: Working, track_id: str, changes: Dict[str, Any]) -> str:
    candidate = copy.deepcopy(w.data)
    tracks = candidate.get("audio_tracks", [])
    for i, track in enumerate(tracks):
        if track.get("id") == track_id:
            tracks[i] = merge(track, changes)
            return w.commit(candidate, f"Changed audio track {track_id} "
                                       f"({', '.join(sorted(changes))})")
    raise ToolFailed(f"No audio track {track_id!r}.")


def remove_audio_track(w: Working, track_id: str) -> str:
    w.track(track_id)
    candidate = copy.deepcopy(w.data)
    candidate["audio_tracks"] = [t for t in candidate["audio_tracks"] if t.get("id") != track_id]
    return w.commit(candidate, f"Removed audio track {track_id}")


_PROJECT_KEYS = ("title", "style", "output", "voice", "chrome", "credits")


def set_project(w: Working, changes: Dict[str, Any]) -> str:
    if not isinstance(changes, dict) or not changes:
        raise ToolFailed("changes must be an object.")
    unknown = sorted(set(changes) - set(_PROJECT_KEYS))
    if unknown:
        raise ToolFailed(f"set_project changes only {', '.join(_PROJECT_KEYS)}; "
                         f"not {', '.join(unknown)}. Segments and tracks have their own tools.")
    candidate = merge(w.data, changes)
    return w.commit(candidate, f"Changed the project's {', '.join(sorted(changes))}")


def run_estimate(w: Working) -> str:
    spec, issues = parse_spec(w.data)
    if spec is None:
        return "Can't estimate yet; the video has issues:\n" + _issues_text(issues)
    result = estimate(spec)
    return _compact({"seconds": result.seconds, "seconds_is_floor": result.seconds_is_floor,
                     "narration_chars": result.narration_chars,
                     "blocks_full_render": result.blocks_render})


# ── schemas ───────────────────────────────────────────────────────────────────

_OBJ = {"type": "object"}
_STR = {"type": "string"}
_NUM = {"type": "number"}

TOOLS: List[Tuple[ToolSpec, Callable[..., str]]] = [
    (ToolSpec("get_spec", "The video as it stands now (after this turn's edits), or one "
              "segment of it.",
              {"type": "object", "properties": {"segment_id": _STR}}), get_spec),
    (ToolSpec("search_assets",
              "Search the user's asset library (GAM) by name, description and what is SAID in "
              "videos. A hit on speech carries said_at [start, end] seconds: the moment to cut "
              "to. Use type to restrict to video, image or audio. An audio hit may carry "
              "kind (music, speech or sfx) and music: its genres, moods, instruments, bpm, "
              "key, energy and vocals, which are also searchable, so search music by the "
              "sound you want.",
              {"type": "object", "properties": {
                  "query": _STR, "type": {"type": "string", "enum": ["video", "image", "audio"]},
                  "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_HITS}},
               "required": ["query"]}), search_assets),
    (ToolSpec("get_asset", "Details of one library asset by gam_id.",
              {"type": "object", "properties": {"gam_id": _STR}, "required": ["gam_id"]}),
     get_asset),
    (ToolSpec("replace_spec",
              "Replace the whole video with a complete VideoSpec. For a first draft or a full "
              "rewrite only; use the targeted tools for anything smaller. Library assets go in "
              "`assets` as {\"from\":\"gam\",\"id\":<gam_id>,\"type\":...}.",
              {"type": "object", "properties": {"spec": _OBJ}, "required": ["spec"]}),
     replace_spec),
    (ToolSpec("add_segment",
              "Insert a segment (scene, card or clip) after the segment `after` (\"start\" for "
              "first, omit for last). A missing or taken id is replaced with a fresh one.",
              {"type": "object", "properties": {"segment": _OBJ, "after": _STR},
               "required": ["segment"]}), add_segment),
    (ToolSpec("update_segment",
              "Change fields of one segment by merge patch: objects merge, null removes a "
              "field, lists (beats, overlays) are replaced whole.",
              {"type": "object", "properties": {"segment_id": _STR, "changes": _OBJ},
               "required": ["segment_id", "changes"]}), update_segment),
    (ToolSpec("move_segment", "Move a segment to after another (\"start\" for first).",
              {"type": "object", "properties": {"segment_id": _STR, "after": _STR},
               "required": ["segment_id", "after"]}), move_segment),
    (ToolSpec("remove_segment", "Remove a segment. Says what was anchored to it.",
              {"type": "object", "properties": {"segment_id": _STR},
               "required": ["segment_id"]}), remove_segment),
    (ToolSpec("set_visual",
              "Set a segment's picture or footage: gam_id (from search_assets, registered for "
              "you) or asset (an existing registry key). A video hit's said_at becomes the trim "
              "unless trim is given. motion and fit as in the spec.",
              {"type": "object", "properties": {
                  "segment_id": _STR, "gam_id": _STR, "asset": _STR, "trim": _OBJ,
                  "motion": _OBJ, "fit": {"type": "string", "enum": ["blur", "pad", "crop"]},
                  "audio": {"type": "string", "enum": ["mute", "play"]},
                  "loop": {"type": "boolean"}},
               "required": ["segment_id"]}), set_visual),
    (ToolSpec("import_note_media",
              "Copy pictures, videos or sounds out of an attached note into the user's library "
              "(GAM) and register them in the video's assets, returning each one's asset key. "
              "Use it when the user wants the note's own media in the video; then place each "
              "with set_visual, add_overlay or add_audio_track, on the scene that covers the "
              "heading it sat under. Takes ids from the note's file list (n1, n2…).",
              {"type": "object", "properties": {"media_ids": {"type": "array", "items": _STR}},
               "required": ["media_ids"]}), import_note_media),
    (ToolSpec("add_placeholder",
              "When the library has nothing fitting: a placeholder for footage still to find "
              "(kind search, text = what to look for) or a picture to generate (kind generate, "
              "text = the prompt), set as the segment's visual. Never invent a gam_id.",
              {"type": "object", "properties": {
                  "segment_id": _STR, "kind": {"type": "string", "enum": ["search", "generate"]},
                  "text": _STR, "media_type": {"type": "string",
                                               "enum": ["video", "image", "audio", "music", "sfx"]},
                  "moment_min": _NUM, "moment_max": _NUM},
               "required": ["segment_id", "kind", "text"]}), add_placeholder),
    (ToolSpec("add_overlay",
              "Add an overlay to a segment: text, lower_third, image (pass gam_id for the "
              "picture), quote or code. show {from, to} anchors default to the segment.",
              {"type": "object", "properties": {"segment_id": _STR, "overlay": _OBJ,
                                                "gam_id": _STR},
               "required": ["segment_id", "overlay"]}), add_overlay),
    (ToolSpec("update_overlay", "Change an overlay by merge patch.",
              {"type": "object", "properties": {"segment_id": _STR, "overlay_id": _STR,
                                                "changes": _OBJ},
               "required": ["segment_id", "overlay_id", "changes"]}), update_overlay),
    (ToolSpec("remove_overlay", "Remove an overlay.",
              {"type": "object", "properties": {"segment_id": _STR, "overlay_id": _STR},
               "required": ["segment_id", "overlay_id"]}), remove_overlay),
    (ToolSpec("add_audio_track",
              "Add music, a sound effect or voice from the library (gam_id from search_assets "
              "with type audio), with start/end anchors, volume and fades.",
              {"type": "object", "properties": {"track": _OBJ, "gam_id": _STR},
               "required": ["track"]}), add_audio_track),
    (ToolSpec("update_audio_track", "Change an audio track by merge patch.",
              {"type": "object", "properties": {"track_id": _STR, "changes": _OBJ},
               "required": ["track_id", "changes"]}), update_audio_track),
    (ToolSpec("remove_audio_track", "Remove an audio track.",
              {"type": "object", "properties": {"track_id": _STR}, "required": ["track_id"]}),
     remove_audio_track),
    (ToolSpec("set_project",
              "Change project-wide settings by merge patch: title, style (default transition, "
              "motion, background, cards…), output, voice, chrome, credits.",
              {"type": "object", "properties": {"changes": _OBJ}, "required": ["changes"]}),
     set_project),
    (ToolSpec("generate_image",
              "Generate a still picture with AI and put it in the video (as a segment's "
              "picture, an image overlay, or just in the registry). It starts at once and "
              "costs money, so search the library first and generate only what a library "
              "can't have. base_gam_ids: library pictures to edit or restyle. Never use "
              "this for video; leave video as a placeholder for the user.",
              {"type": "object", "properties": {
                  "prompt": _STR, "segment_id": _STR,
                  "use_as": {"type": "string", "enum": ["visual", "overlay", "none"]},
                  "base_gam_ids": {"type": "array", "items": _STR},
                  "outputs": {"type": "integer", "minimum": 1, "maximum": 4},
                  "label": _STR},
               "required": ["prompt"]}), generate_image),
    (ToolSpec("estimate", "How long the video runs, its narration length, and what would "
              "stop a full render.", {"type": "object", "properties": {}}), run_estimate),
]

SPECS = [spec for spec, _ in TOOLS]
_HANDLERS = {spec.name: handler for spec, handler in TOOLS}

# Read-only tools, which neither change the video nor count as an edit in the steps.
READS = {"get_spec", "search_assets", "get_asset", "estimate"}


def execute(w: Working, call: ToolCall) -> ToolResult:
    """Run one call. Never raises: a failure is a result the model reads and acts on."""
    if call.parse_error:
        return ToolResult(call.id, f"Your arguments couldn't be read: {call.parse_error}.",
                          is_error=True)
    handler = _HANDLERS.get(call.name)
    if handler is None:
        return ToolResult(call.id, f"There is no tool {call.name!r}.", is_error=True)
    try:
        return ToolResult(call.id, handler(w, **call.arguments))
    except ToolFailed as exc:
        return ToolResult(call.id, str(exc), is_error=True)
    except TypeError as exc:
        # Arguments the handler doesn't take: said in the schema's terms.
        return ToolResult(call.id, f"Wrong arguments for {call.name}: {exc}", is_error=True)
