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
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.assistant import clips
from app.gam.client import GamClient, GamError
from app.providers.base import ProviderError, ToolCall, ToolResult, ToolSpec
from app.schemas_gam import GamAssetRead, GamDocumentPage, GamTranscript
from app.render.estimate import estimate
from app.services import note_media as note_files
from app.schemas_recipes import MAX_RECIPE_NAME, MAX_RECIPE_PROMPT, RecipeDefaults
from app.schemas_themes import MAX_THEME_NAME, MAX_THEME_PROMPT
from app.services import recipes as recipe_rules
from app.services.themes import theme_id_of
from app.spec.validation import SpecIssue, parse_spec
from app.spec.model import MAX_WEB_CANDIDATES

# A found moment is padded so a cut doesn't clip a word: the editor's `momentTrim`.
MOMENT_PAD = 0.5
DEFAULT_MOMENT_SECONDS = 5.0
MAX_SEARCH_HITS = 12
# A transcript is read in pages of about 8k tokens. Every result stays in the turn's
# conversation and is sent again each round, so an hour of speech in one call would cost
# far more than reading the stretch around what was found.
MAX_TRANSCRIPT_CHARS = 30_000
# A document is read in pages of the same size, for the same reason: a 200-page report
# in one result would be sent again every round of the turn.
MAX_DOCUMENT_CHARS = 30_000
# Where a sentence ends: closing punctuation, then any closing quotes or brackets.
SENTENCE_END = re.compile(r"[.?!\u2026][\"'\u201d\u2019)\]]*$")
# Unpunctuated speech would make one endless "sentence"; past this a line is closed at
# the next word anyway, so every line stays small enough to be a cut.
MAX_SENTENCE_SECONDS = 30.0
# How far the automatic cut may grow to take in the whole sentence around a found moment.
# Enough for a long sentence, not so much that a run-on line swallows the video.
MAX_SENTENCE_STRETCH = 12.0
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
class Sentence:
    start: float
    end: float
    text: str
    speaker: Optional[int] = None


def sentences(transcript: GamTranscript) -> List[Sentence]:
    """What was said, as sentences timed from the words.

    Not the transcriber's segments: those end wherever the speaker paused, often halfway
    through a sentence, and a cut taken from one starts or stops mid-thought. That is the
    bad timestamp this exists to prevent.
    """
    out: List[Sentence] = []
    words: List[Tuple[str, float, float]] = []
    speaker: Optional[int] = None

    def close() -> None:
        if words:
            out.append(Sentence(words[0][1], words[-1][2],
                                " ".join(text for text, _, _ in words), speaker))
            words.clear()

    for segment in transcript.segments:
        if segment.speaker != speaker:
            close()
            speaker = segment.speaker
        units = [] if segment.edited else [
            (w.text.strip(), w.start_time, w.end_time) for w in segment.words if w.text.strip()]
        if not units and segment.text.strip():
            # No usable word timings (an older transcript, or one corrected by hand): the
            # segment is the smallest thing with a time on it.
            units = [(segment.text.strip(), segment.start_time, segment.end_time)]
        for text, start, end in units:
            if words and start - words[0][1] > MAX_SENTENCE_SECONDS:
                close()
            words.append((text, start, end))
            if SENTENCE_END.search(text):
                close()
    close()
    return out


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
    # Transcripts fetched this turn by gam_id, so reading one and then cutting from it
    # asks GAM once.
    transcripts: Dict[str, GamTranscript] = field(default_factory=dict)
    # Documents read this turn by gam_id, with the asset, so reading on asks GAM once.
    documents: Dict[str, Tuple[GamAssetRead, List[GamDocumentPage]]] = field(default_factory=dict)
    # One model call with no tools: (system, prompt) -> the reply's text, its spend
    # recorded against the turn. Set by the worker; None where there is no provider,
    # and then find_clips says to read the transcript instead.
    ask: Optional[Callable[[str, str], str]] = None
    # Calls the clip-picking pass may make in one turn (a long video takes several),
    # and what it found, so asking the same thing twice pays once.
    max_picks: int = 16
    picks: int = 0
    picked: Dict[Tuple[str, str, int], str] = field(default_factory=dict)
    # Picker calls made at once: across the videos of one round, and the windows of a
    # long one. `ask` must be safe to call from several threads.
    pick_concurrency: int = 4
    # The user's themes by id: {"name", "prompt"}. The only ids `style.theme` may be
    # set to, since an id the user doesn't own would silently style nothing.
    themes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Adds a theme to the user's list: (name, prompt) -> its id. Set by the worker; None
    # where there is no database to write to, and then create_theme says so.
    add_theme: Optional[Callable[[str, str], str]] = None
    max_new_themes: int = 2
    new_themes: int = 0
    # Change or delete one of the user's themes, now: (id, name, prompt, is_default),
    # None leaving a field alone; and (id). Set by the worker, like add_theme.
    edit_theme: Optional[Callable[[str, Optional[str], Optional[str], Optional[bool]],
                                  None]] = None
    remove_theme: Optional[Callable[[str], None]] = None
    # Edits and deletes one request may make. Each restyles every project using the
    # theme, so a model looping on them should be stopped well before the round limit.
    max_theme_changes: int = 4
    theme_changes: int = 0
    # The web: `query -> results`, through Gecko Suite. Set by the worker only when the
    # assistant runs there; None otherwise, and then the tool is not offered at all
    # (`specs_for`), so a model is never told about a tool it cannot use.
    web_search: Optional[Callable[[str], List[Dict[str, Any]]]] = None
    web_searches: int = 0
    max_web_searches: int = 8
    # Pictures on the web, the same way: `query -> candidates`. A turn may look a few
    # times; each look leaves one placeholder for the person to choose on.
    image_search: Optional[Callable[[str], List[Dict[str, Any]]]] = None
    image_searches: int = 0
    max_image_searches: int = 6
    # Notes proposed for Gecko Notes this turn. Offered only where the turn holds the
    # person's token (`can_note`), which is what creating one on Apply will forward.
    can_note: bool = False
    notes: List[Dict[str, Any]] = field(default_factory=list)
    max_notes: int = 3
    # The user's recipes by id, as saved: {"name", "prompt", "tags", "defaults",
    # "updated_at"}. Read by list_recipes and get_recipe, and the only ids a proposal may
    # name, since the model chooses them.
    recipes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Changes to that list proposed this turn, each saved only by its own button
    # (routers/assistant.py), never here: [{"recipe_ref", "op", "recipe_id", "before",
    # "after", "fields", "base_updated_at", "state"}].
    recipe_proposals: List[Dict[str, Any]] = field(default_factory=list)
    # Updates are the common ask ("retag these four"), so they get more room than new ones.
    max_recipe_proposals: int = 6
    max_new_recipes: int = 3

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

    def transcript(self, gam_id: str) -> GamTranscript:
        if gam_id not in self.transcripts:
            if self.gam is None:
                raise ToolFailed("The asset library isn't reachable in this turn.")
            try:
                found = self.gam.transcript(gam_id)
            except GamError as exc:
                raise ToolFailed(f"The asset library failed: {exc.message}")
            if found is None:
                raise ToolFailed(f"No asset {gam_id!r} in the library.")
            self.transcripts[gam_id] = found
        return self.transcripts[gam_id]

    def document(self, gam_id: str) -> Tuple[GamAssetRead, List[GamDocumentPage]]:
        if gam_id not in self.documents:
            if self.gam is None:
                raise ToolFailed("The asset library isn't reachable in this turn.")
            try:
                # The asset first: it is what tells "not in the library" from a GAM
                # that has no text route, which both answer the text call with a 404.
                asset = self.gam.get_asset(gam_id)
                if asset is None:
                    raise ToolFailed(f"No asset {gam_id!r} in the library.")
                pages = self.gam.document_text(gam_id)
            except GamError as exc:
                raise ToolFailed(f"The asset library failed: {exc.message}")
            if pages is None:
                raise ToolFailed("This version of the asset library can't hand over a "
                                 "document's text. GAM needs updating.")
            self.documents[gam_id] = (asset, pages)
        return self.documents[gam_id]

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
        theme = theme_id_of(candidate)
        if theme != theme_id_of(self.data) and theme is not None and theme not in self.themes:
            raise ToolFailed(f"There is no theme {theme!r}. Use set_theme with one of the "
                             "themes listed in the context.")
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
        if hit.other_matches:
            # GAM shows each asset's best moment only; this says the rest is worth reading.
            row["more_moments"] = hit.other_matches
        if hit.page_label:
            # Where in a document it is written: read_document's start for that part.
            row["page"] = hit.page_label
            if hit.page_number is not None:
                row["page_number"] = hit.page_number
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
    if asset.asset_type == "document":
        details["text"] = "read_document reads it"
    return _compact(details)


def read_transcript(w: Working, gam_id: str, start: Optional[float] = None,
                    end: Optional[float] = None) -> str:
    lines = [s for s in sentences(w.transcript(gam_id))
             if (start is None or s.end > start) and (end is None or s.start < end)]
    if not lines:
        if start is not None or end is not None:
            return "Nothing is said in that stretch."
        return ("This asset has no transcript: it hasn't been transcribed in the library, or "
                "nothing is said in it.")
    speakers = len({s.speaker for s in lines if s.speaker is not None}) > 1
    out: List[str] = []
    size, rest, previous = 0, None, object()
    for s in lines:
        who = f"S{s.speaker}: " if speakers and s.speaker != previous else ""
        line = f"[{s.start:.1f}-{s.end:.1f}] {who}{s.text}"
        if out and size + len(line) > MAX_TRANSCRIPT_CHARS:
            rest = s.start
            break
        out.append(line)
        size += len(line) + 1
        previous = s.speaker
    head = ("One sentence per line, [start-end] in seconds. A trim from one line's start to "
            "a later line's end cuts whole sentences.")
    tail = (f"\n... continues: read_transcript with start {rest:.1f} for the rest."
            if rest is not None else "")
    return head + "\n" + "\n".join(out) + tail


def read_document(w: Working, gam_id: str, start: Optional[int] = None,
                  end: Optional[int] = None) -> str:
    asset, pages = w.document(gam_id)
    if not pages:
        if asset.asset_type in ("video", "audio"):
            return "This is a recording, not a document: read_transcript reads what is said in it."
        if asset.asset_type != "document":
            return f"This is {'an' if asset.asset_type[:1] in 'aeiou' else 'a'} " \
                   f"{asset.asset_type or 'asset'}, which has no text to read."
        return ("The library has no text for this document yet. It reads a document's text "
                "when the file arrives, so it may still be reading it; a scanned document, or "
                "an old .doc, .xls or .ppt file, has none it can read. Say so rather than "
                "guess what it says.")
    chosen = [p for p in pages
              if (start is None or p.number >= start) and (end is None or p.number <= end)]
    if not chosen:
        known = f"{pages[0].number}-{pages[-1].number}"
        return f"No part of this document is numbered in that range. Its parts run {known}."
    out: List[str] = []
    size, rest = 0, None
    for p in chosen:
        text = p.text.strip()
        head = f"--- [{p.number}] {p.label or f'Part {p.number}'} ---"
        if out and size + len(head) + len(text) > MAX_DOCUMENT_CHARS:
            rest = p.number
            break
        if len(text) > MAX_DOCUMENT_CHARS:
            # One part longer than a whole read (a big spreadsheet's sheet): its opening,
            # said to be cut, rather than a read that can never make progress.
            text = text[:MAX_DOCUMENT_CHARS] + "\n[the rest of this part is cut off]"
        out.append(head + "\n" + text)
        size += len(head) + len(text) + 2
    lead = (f"{asset.name}: {len(pages)} part{'' if len(pages) == 1 else 's'}. Each starts "
            "with [n] and its label; start/end take n. Quote it as written, and say which "
            "part a quote came from.")
    tail = (f"\n... continues: read_document with start {rest} for the rest."
            if rest is not None else "")
    return lead + "\n" + "\n\n".join(out) + tail


@dataclass
class ClipJob:
    """A find_clips call checked and budgeted, its picker calls still to make.

    Split from the calls themselves so a round that asks for clips from several videos
    can make every picker call at once (`finish_clip_jobs`): each is a slow model call,
    and one after another they were most of the wait.
    """

    key: Tuple[str, str, int]
    gam_id: str
    idea: str
    count: int
    lines: List[Sentence]
    spans: List[Tuple[int, int]]
    prompts: List[str]
    duration: Optional[float]


def plan_clips(w: Working, gam_id: str, idea: str, count: int = 3) -> "str | ClipJob":
    """The job for a find_clips call, or its whole answer when no picker call is needed
    (already asked this turn, or nothing is said in the video)."""
    if w.ask is None:
        raise ToolFailed("Clip picking isn't available in this turn; use read_transcript.")
    if not (idea or "").strip():
        raise ToolFailed("Say the idea the clip has to put across.")
    try:
        count = max(1, min(5, int(count)))
    except (TypeError, ValueError):
        raise ToolFailed("count must be a whole number from 1 to 5.")
    key = (gam_id, idea.strip().lower(), count)
    if key in w.picked:
        return w.picked[key]
    lines = sentences(w.transcript(gam_id))
    if not lines:
        return ("This asset has no transcript: it hasn't been transcribed in the library, or "
                "nothing is said in it.")
    spans = clips.windows(lines)
    left = w.max_picks - w.picks
    if len(spans) > left:
        raise ToolFailed(f"Clip picking has {left} of its {w.max_picks} calls left this turn "
                         f"and this video needs {len(spans)}. Use read_transcript around a "
                         "search hit's said_at instead.")
    # Taken now, not as the calls finish: the calls of one round run together, and each
    # job has to see what the ones planned before it will spend.
    w.picks += len(spans)
    seen = w.hits.get(gam_id)
    name = seen.name if seen else None
    return ClipJob(key=key, gam_id=gam_id, idea=idea.strip(), count=count, lines=lines,
                   spans=spans,
                   prompts=[clips.prompt_for(idea, count, lines, span, name) for span in spans],
                   duration=seen.duration if seen else None)


def finish_clip_jobs(w: Working, jobs: List[ClipJob]) -> List[Tuple[str, bool]]:
    """Make every picker call of these jobs, up to `pick_concurrency` at once, and give
    each job's answer as (content, is_error), in the order the jobs came."""
    texts: List[List[str]] = [[""] * len(job.prompts) for job in jobs]
    failed: List[Optional[str]] = [None] * len(jobs)
    calls = [(j, i) for j, job in enumerate(jobs) for i in range(len(job.prompts))]
    if calls:
        workers = max(1, min(w.pick_concurrency, len(calls)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clip-pick") as pool:
            futures = {pool.submit(w.ask, clips.SYSTEM, jobs[j].prompts[i]): (j, i)
                       for j, i in calls}
            for future in as_completed(futures):
                j, i = futures[future]
                try:
                    texts[j][i] = future.result()
                except ProviderError as exc:
                    # One video's failure is that video's answer; the others still stand.
                    failed[j] = failed[j] or str(exc)
    out: List[Tuple[str, bool]] = []
    for job, answers, error in zip(jobs, texts, failed):
        if error:
            out.append((f"The clip-picking pass failed ({error}). Use read_transcript and "
                        "choose the passage yourself.", True))
        else:
            out.append((_clips_result(w, job, answers), False))
    return out


def _clips_result(w: Working, job: ClipJob, answers: List[str]) -> str:
    found: List[clips.Clip] = []
    for span, text in zip(job.spans, answers):
        found += clips.parse(text, job.lines, span)
    chosen = clips.best(found, job.count)
    lines = job.lines
    if not chosen:
        result = ("Nothing in this video makes that point well. Try another video, or "
                  "describe the idea differently.")
    else:
        rows = []
        for clip in chosen:
            first, last = lines[clip.first], lines[clip.last]
            said = " ".join(lines[i].text for i in range(clip.first, clip.last + 1))
            rows.append({
                "trim": _padded(first.start, last.end, lines, clip.first, clip.last,
                                job.duration),
                "seconds": round(last.end - first.start, 1),
                "score": clip.score,
                "why": clip.why,
                "says": said if len(said) <= 400 else said[:400] + "…",
            })
        result = _compact({"gam_id": job.gam_id, "idea": job.idea, "clips": rows})
    w.picked[job.key] = result
    return result


def find_clips(w: Working, gam_id: str, idea: str, count: int = 3) -> str:
    planned = plan_clips(w, gam_id, idea, count)
    if isinstance(planned, str):
        return planned
    [(content, is_error)] = finish_clip_jobs(w, [planned])
    if is_error:
        raise ToolFailed(content)
    return content


def replace_spec(w: Working, spec: Dict[str, Any]) -> str:
    if not isinstance(spec, dict):
        raise ToolFailed("spec must be a VideoSpec object.")
    candidate = copy.deepcopy(spec)
    # The project owns its id; a draft never changes it.
    if "id" in w.data:
        candidate["id"] = w.data["id"]
    # A whole draft seldom restates the theme, and leaving it out isn't a decision to
    # drop it: the theme stays unless the draft names another of the user's. Removing
    # it is set_theme's job, where it is said on purpose.
    style = candidate.setdefault("style", {})
    if isinstance(style, dict):
        named = style.get("theme")
        if named is None or (named not in w.themes and named != theme_id_of(w.data)):
            style.pop("theme", None)
            if theme_id_of(w.data):
                style["theme"] = theme_id_of(w.data)
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


def _padded(a: float, b: float, lines: List[Sentence], first: Optional[int],
            last: Optional[int], duration: Optional[float]) -> Optional[Dict[str, float]]:
    """[a, b] as a trim, padded so a cut doesn't clip a word, but never into the
    sentences either side of lines first..last."""
    floor = lines[first - 1].end if first else 0.0
    ceiling = lines[last + 1].start if last is not None and last + 1 < len(lines) else None
    a = max(floor, a - MOMENT_PAD)
    b = b + MOMENT_PAD if ceiling is None else min(b + MOMENT_PAD, max(b, ceiling))
    if duration:
        b = min(b, duration)
    return {"in": round(a, 1), "out": round(b, 1)} if b > a else None


def _moment_trim(hit: Hit, lines: List[Sentence] = ()) -> Optional[Dict[str, float]]:
    """The found moment as a cut, grown to the whole sentences it falls in when the
    transcript is to hand."""
    if hit.start is None:
        return None
    a = hit.start
    b = hit.end if hit.end is not None else hit.start + DEFAULT_MOMENT_SECONDS
    touching = [i for i, s in enumerate(lines) if s.end > a and s.start < b]
    first = last = None
    if touching:
        first, last = touching[0], touching[-1]
        if a - lines[first].start <= MAX_SENTENCE_STRETCH:
            a = min(a, lines[first].start)
        if lines[last].end - b <= MAX_SENTENCE_STRETCH:
            b = max(b, lines[last].end)
    return _padded(a, b, lines, first, last, hit.duration)


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
    elif hit and hit.asset_type == "video" and hit.start is not None:
        # The moment that was said becomes the cut, as picking a hit does in the editor,
        # grown to whole sentences. Without the transcript it is still the moment.
        try:
            lines = sentences(w.transcript(hit.gam_id))
        except ToolFailed:
            lines = []
        moment = _moment_trim(hit, lines)
        if moment:
            visual["trim"] = moment
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


def set_theme(w: Working, theme: Optional[str] = None) -> str:
    """Choose the video's theme from the user's list, by name or id; none removes it."""
    if theme is not None and not isinstance(theme, str):
        raise ToolFailed("theme is a theme's name or id, as text.")
    candidate = copy.deepcopy(w.data)
    style = candidate.setdefault("style", {})
    if theme is None or not theme.strip() or theme.strip().lower() == "none":
        style.pop("theme", None)
        return w.commit(candidate, "Removed the theme")
    found = _find_theme(w, theme)
    style["theme"] = found
    return w.commit(candidate, f"Set the theme to {w.themes[found]['name']!r}")


def _find_theme(w: Working, theme: Any) -> str:
    """The id of one of the user's themes, given its id or its name (any case)."""
    if not isinstance(theme, str) or not theme.strip():
        raise ToolFailed("Say which theme, by its name or id.")
    wanted = theme.strip()
    found = wanted if wanted in w.themes else next(
        (tid for tid, t in w.themes.items() if t["name"].strip().lower() == wanted.lower()),
        None)
    if found is None:
        names = ", ".join(repr(t["name"]) for t in w.themes.values()) or "none; the user " \
            "hasn't made any (they are made in Settings)"
        raise ToolFailed(f"No theme {wanted!r}. The themes are: {names}.")
    return found


def create_theme(w: Working, name: str, prompt: str, use: bool = False) -> str:
    """A new theme in the user's list, made now; the video's theme too only with `use`.

    Not used by default: "make me a noir theme" is a request about the list, and
    quietly restyling the open video, or turning a theme request on the project list
    into a new video, isn't what was asked.

    Made at once rather than on Apply, as generate_image starts at once: a theme is an
    entry in the user's list, not part of the video, so it has no place in a proposal,
    and the spec can only name a theme that exists. Discarding the proposal leaves the
    theme in the list, where the user can delete it; the reply has to say it was made.
    """
    if w.add_theme is None:
        raise ToolFailed("Making themes isn't available in this turn.")
    if not isinstance(name, str) or not name.strip():
        raise ToolFailed("Give the theme a short name.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ToolFailed("Write the theme's text: the look it adds to every prompt.")
    name, prompt = name.strip(), prompt.strip()
    if len(name) > MAX_THEME_NAME or len(prompt) > MAX_THEME_PROMPT:
        raise ToolFailed(f"A theme's name is at most {MAX_THEME_NAME} characters and its "
                         f"text at most {MAX_THEME_PROMPT}.")
    taken = next((tid for tid, t in w.themes.items()
                  if t["name"].strip().lower() == name.lower()), None)
    if taken is not None:
        raise ToolFailed(f"There is already a theme called {w.themes[taken]['name']!r}; "
                         "use set_theme for it, or choose another name.")
    if w.new_themes >= w.max_new_themes:
        raise ToolFailed(f"That's the {w.max_new_themes} themes one request may make. Use "
                         "one of the themes listed with set_theme.")
    theme_id = w.add_theme(name, prompt)
    w.new_themes += 1
    w.themes[theme_id] = {"name": name, "prompt": prompt}
    made = f"Made the theme {name!r} in the user's list (id {theme_id})."
    if not use:
        return made
    return f"{made} {set_theme(w, theme_id)}"


def _theme_change_allowed(w: Working) -> None:
    if w.theme_changes >= w.max_theme_changes:
        raise ToolFailed(f"That's the {w.max_theme_changes} theme changes one request may "
                         "make. Tell the user what is left to do.")


def update_theme(w: Working, theme: str, name: Optional[str] = None,
                 prompt: Optional[str] = None, make_default: Optional[bool] = None) -> str:
    """Change one of the user's themes, now.

    Made at once, as create_theme is: a theme is the user's list, not this video. The
    result carries what it was, so the reply can say how to put it back, since an edit
    restyles every project using the theme and there is no undo for the list.
    """
    if w.edit_theme is None:
        raise ToolFailed("Changing themes isn't available in this turn.")
    found = _find_theme(w, theme)
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise ToolFailed("A theme's name can't be empty.")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        raise ToolFailed("A theme's text can't be empty; to stop using it, delete it or "
                         "set another theme.")
    if make_default is not None and not isinstance(make_default, bool):
        raise ToolFailed("make_default is true or false.")
    if name is None and prompt is None and make_default is None:
        raise ToolFailed("Say what to change: name, prompt or make_default.")
    name = name.strip() if name is not None else None
    prompt = prompt.strip() if prompt is not None else None
    if (name and len(name) > MAX_THEME_NAME) or (prompt and len(prompt) > MAX_THEME_PROMPT):
        raise ToolFailed(f"A theme's name is at most {MAX_THEME_NAME} characters and its "
                         f"text at most {MAX_THEME_PROMPT}.")
    if name is not None and any(t["name"].strip().lower() == name.lower()
                                for tid, t in w.themes.items() if tid != found):
        raise ToolFailed(f"There is already a theme called {name!r}.")
    _theme_change_allowed(w)
    before = dict(w.themes[found])
    w.edit_theme(found, name, prompt, make_default)
    w.theme_changes += 1
    # Entries are replaced, never changed in place: the worker's dict is the turn's
    # own, but nothing here should depend on that.
    if make_default:
        w.themes = {tid: {**t, "is_default": False} for tid, t in w.themes.items()}
    after = {**w.themes[found],
             **{k: v for k, v in (("name", name), ("prompt", prompt),
                                  ("is_default", make_default)) if v is not None}}
    w.themes[found] = after
    changed = [f"{field} was {before.get(field)!r}" for field, value in
               (("name", name), ("prompt", prompt), ("is_default", make_default))
               if value is not None]
    return (f"Changed the theme {after['name']!r} in the user's list ({'; '.join(changed)}). "
            "Every project using it generates with the new version from now on.")


def delete_theme(w: Working, theme: str) -> str:
    """Delete one of the user's themes, now. Projects naming it generate unstyled; this
    video, if it is one of them, stops naming it."""
    if w.remove_theme is None:
        raise ToolFailed("Deleting themes isn't available in this turn.")
    found = _find_theme(w, theme)
    _theme_change_allowed(w)
    gone = w.themes[found]
    w.remove_theme(found)
    w.theme_changes += 1
    del w.themes[found]
    result = (f"Deleted the theme {gone['name']!r} from the user's list. Its text was "
              f"{gone['prompt']!r}. Other projects using it now generate without a theme.")
    if theme_id_of(w.data) == found:
        candidate = copy.deepcopy(w.data)
        candidate["style"].pop("theme", None)
        result += " " + w.commit(candidate, "Removed the deleted theme")
    return result


# What one search may hand back to the model: a page of results, not a crawl.
MAX_WEB_CHARS = 6_000


NOTE_MAX = 50_000


def propose_note(w: Working, title: str, markdown: str, folder: Optional[str] = None) -> str:
    """A note for Gecko Notes, made only when the person presses its button.

    Not a change to the video, so it is kept apart from `w.changes` and the proposed spec:
    a turn may propose a note, an edit, or both, and each is decided on its own. The same
    title again rewrites that note, so a model correcting itself does not leave two.
    """
    title, markdown = (title or "").strip(), markdown or ""
    if not title or not markdown.strip():
        raise ToolFailed("Give the note a title and its text, in Markdown.")
    if len(title) > 200:
        raise ToolFailed("The title is at most 200 characters.")
    if len(markdown) > NOTE_MAX:
        raise ToolFailed(f"The note is too long ({len(markdown)} of {NOTE_MAX} characters). "
                         "Make it shorter, or split it into notes.")
    held = next((n for n in w.notes if n["title"].lower() == title.lower()), None)
    if held is None and len(w.notes) >= w.max_notes:
        raise ToolFailed(f"That's the {w.max_notes} notes one request may propose.")
    folder = (folder or "").strip()[:120] or None
    entry = {"note_ref": held["note_ref"] if held else uuid.uuid4().hex,
             "title": title, "markdown": markdown, "folder": folder, "state": "pending",
             "note_url": None}
    if held:
        w.notes[w.notes.index(held)] = entry
    else:
        w.notes.append(entry)
    return (f"Proposed the note {title!r} for Gecko Notes ({len(markdown)} characters). "
            "The user creates it with the button on your reply; say so, never that it exists.")


# ── recipes ───────────────────────────────────────────────────────────────────

# Told apart from an explicit null: in an update, a field left out stays as it is, and a
# null clears it (a theme, an aspect, a voice).
_UNSET: Any = object()
RECIPE_OPS = ("create", "update", "delete")


def _recipe_draft(name: str, prompt: str, tags: List[str], defaults: Dict[str, Any]
                  ) -> Dict[str, Any]:
    return {"name": name, "prompt": prompt, "tags": tags, "defaults": defaults,
            "inputs": recipe_rules.inputs_of(prompt)}


def _find_recipe(w: Working, recipe: Any) -> str:
    """The id of one of the user's recipes, given its id or its name (any case)."""
    if not isinstance(recipe, str) or not recipe.strip():
        raise ToolFailed("Say which recipe, by its name or id.")
    wanted = recipe.strip()
    if wanted in w.recipes:
        return wanted
    named = [rid for rid, r in w.recipes.items()
             if r["name"].strip().lower() == wanted.lower()]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        raise ToolFailed(f"More than one recipe is called {wanted!r}; give its id "
                         "(list_recipes).")
    names = ", ".join(repr(r["name"]) for r in w.recipes.values()) or \
        "none; the user hasn't saved any"
    raise ToolFailed(f"No recipe {wanted!r}. The recipes are: {names}.")


def list_recipes(w: Working, tag: Optional[str] = None) -> str:
    """The user's recipes, enough to choose one: get_recipe has the whole prompt."""
    tag = (tag or "").strip().lower()
    rows = [(rid, r) for rid, r in w.recipes.items() if not tag or tag in r["tags"]]
    if not rows:
        return "No recipes" + (f" tagged {tag!r}." if tag else "; the user hasn't saved any.")
    pending = {p["recipe_id"] for p in w.recipe_proposals if p.get("recipe_id")}
    out = []
    for rid, r in rows:
        prompt = r["prompt"]
        out.append({"id": rid, "name": r["name"], "tags": r["tags"],
                    "inputs": recipe_rules.inputs_of(prompt), "defaults": r["defaults"],
                    "prompt": prompt[:200] + ("…" if len(prompt) > 200 else ""),
                    **({"proposed_change_pending": True} if rid in pending else {})})
    return json.dumps(out, ensure_ascii=False)


def get_recipe(w: Working, recipe: str) -> str:
    """One recipe whole, so an edit is written over its real text, not a preview."""
    rid = _find_recipe(w, recipe)
    r = w.recipes[rid]
    return json.dumps({"id": rid, "name": r["name"], "prompt": r["prompt"], "tags": r["tags"],
                       "inputs": recipe_rules.inputs_of(r["prompt"]),
                       "defaults": r["defaults"]}, ensure_ascii=False)


def _recipe_defaults(w: Working, base: Dict[str, Any], theme: Any, aspect: Any,
                     voice: Any) -> Dict[str, Any]:
    """`base` with the named defaults changed: left out stays, null (or "none") clears."""
    out = dict(base)
    if theme is not _UNSET:
        if theme is None or (isinstance(theme, str) and theme.strip().lower() in ("", "none")):
            out.pop("theme_id", None)
        else:
            out["theme_id"] = _find_theme(w, theme)
    if aspect is not _UNSET:
        if aspect is None or aspect == "":
            out.pop("aspect", None)
        else:
            out["aspect"] = aspect
    if voice is not _UNSET:
        if voice is None or voice == "":
            out.pop("voice", None)
        else:
            if isinstance(voice, str):
                voice = {"voice": voice}
            if not isinstance(voice, dict):
                raise ToolFailed("voice is an object: {provider, voice, speed, expressivity}.")
            out["voice"] = {**(out.get("voice") or {}), **voice}
    try:
        checked = RecipeDefaults.model_validate(out)
    except ValueError as exc:
        raise ToolFailed(f"Those defaults aren't valid: {exc}. aspect is 16:9, 9:16 or 1:1; "
                         "voice is {provider, voice, speed (0.5-2), expressivity (-2..2)}."
                         ) from exc
    return checked.model_dump(mode="json", exclude_none=True)


def _recipe_text(name: Any, prompt: Any) -> None:
    if name is not _UNSET and (not isinstance(name, str) or not name.strip()
                               or len(name.strip()) > MAX_RECIPE_NAME):
        raise ToolFailed(f"A recipe's name is 1 to {MAX_RECIPE_NAME} characters.")
    if prompt is not _UNSET and (not isinstance(prompt, str) or not prompt.strip()
                                 or len(prompt.strip()) > MAX_RECIPE_PROMPT):
        raise ToolFailed(f"A recipe's prompt is 1 to {MAX_RECIPE_PROMPT} characters.")


def _recipe_tags(tags: Any) -> List[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, list):
        raise ToolFailed("tags is a list of short words.")
    return recipe_rules.clean_tags(tags)


def _name_taken(w: Working, name: str, other_than: Optional[str]) -> bool:
    return any(r["name"].strip().lower() == name.lower()
               for rid, r in w.recipes.items() if rid != other_than)


def _hold(w: Working, entry: Dict[str, Any], replacing: Optional[Dict[str, Any]]) -> None:
    if replacing is not None:
        entry["recipe_ref"] = replacing["recipe_ref"]
        w.recipe_proposals[w.recipe_proposals.index(replacing)] = entry
        return
    if len(w.recipe_proposals) >= w.max_recipe_proposals:
        raise ToolFailed(f"That's the {w.max_recipe_proposals} recipe changes one request "
                         "may propose. Tell the user what is left to do.")
    w.recipe_proposals.append(entry)


_SAVE_HINT = ("The user saves it with the button on your reply; say so, never that it is "
              "saved.")


def propose_recipe(w: Working, op: str, recipe: Optional[str] = None, name: Any = _UNSET,
                   prompt: Any = _UNSET, tags: Any = _UNSET, theme: Any = _UNSET,
                   aspect: Any = _UNSET, voice: Any = _UNSET) -> str:
    """Propose a new recipe, a change to one, or deleting one. Nothing is saved here.

    Not a change to the video, so it is kept apart from `w.changes`: a turn may propose an
    edit, a recipe, or both, and each is decided on its own. Proposing for the same recipe
    again rewrites the card rather than adding a second, and an update builds on the one
    already pending, so a model refining its own edit ends with one card holding all of it.
    """
    if op not in RECIPE_OPS:
        raise ToolFailed("op is create, update or delete.")
    _recipe_text(name, prompt)

    if op == "create":
        if name is _UNSET or prompt is _UNSET:
            raise ToolFailed("A new recipe needs a name and a prompt.")
        name, prompt = name.strip(), prompt.strip()
        if _name_taken(w, name, None):
            raise ToolFailed(f"There is already a recipe called {name!r}; propose an update "
                             "to it (op update), or choose another name.")
        held = next((p for p in w.recipe_proposals if p["op"] == "create"
                     and p["after"]["name"].lower() == name.lower()), None)
        if held is None and sum(p["op"] == "create" for p in w.recipe_proposals) \
                >= w.max_new_recipes:
            raise ToolFailed(f"That's the {w.max_new_recipes} new recipes one request may "
                             "propose.")
        defaults = _recipe_defaults(w, {}, theme, aspect, voice)
        after = _recipe_draft(name, prompt, _recipe_tags([] if tags is _UNSET else tags),
                              defaults)
        _hold(w, {"recipe_ref": uuid.uuid4().hex, "op": "create", "recipe_id": None,
                  "before": None, "after": after, "fields": [], "base_updated_at": None,
                  "state": "pending"}, held)
        inputs = ", ".join(after["inputs"]) or "none"
        return f"Proposed the new recipe {name!r} (inputs: {inputs}). {_SAVE_HINT}"

    # A recipe this turn proposed creating isn't saved yet, so changing or deleting it
    # changes or withdraws that proposal.
    made = _pending_create(w, recipe)
    if made is not None:
        if op == "delete":
            w.recipe_proposals.remove(made)
            return f"Withdrew the proposed recipe {made['after']['name']!r}."
        a = made["after"]
        new_name = a["name"] if name is _UNSET else name.strip()
        if _name_taken(w, new_name, None):
            raise ToolFailed(f"There is already a recipe called {new_name!r}.")
        made["after"] = _recipe_draft(
            new_name, a["prompt"] if prompt is _UNSET else prompt.strip(),
            a["tags"] if tags is _UNSET else _recipe_tags(tags),
            _recipe_defaults(w, a["defaults"], theme, aspect, voice))
        return f"Changed the proposed new recipe {new_name!r}. {_SAVE_HINT}"

    rid = _find_recipe(w, recipe)
    saved = w.recipes[rid]
    before = _recipe_draft(saved["name"], saved["prompt"], list(saved["tags"]),
                           dict(saved["defaults"]))
    held = next((p for p in w.recipe_proposals if p.get("recipe_id") == rid), None)

    if op == "delete":
        _hold(w, {"recipe_ref": uuid.uuid4().hex, "op": "delete", "recipe_id": rid,
                  "before": before, "after": None, "fields": [],
                  "base_updated_at": saved["updated_at"], "state": "pending"}, held)
        return f"Proposed deleting the recipe {saved['name']!r}. {_SAVE_HINT}"

    if all(v is _UNSET for v in (name, prompt, tags, theme, aspect, voice)):
        raise ToolFailed("Say what to change: name, prompt, tags, theme, aspect or voice.")
    # Built on the pending update, if any, so a second call adds to the first.
    start = held["after"] if held is not None and held["op"] == "update" else before
    new_name = start["name"] if name is _UNSET else name.strip()
    if _name_taken(w, new_name, rid):
        raise ToolFailed(f"There is already a recipe called {new_name!r}.")
    after = _recipe_draft(new_name, start["prompt"] if prompt is _UNSET else prompt.strip(),
                          start["tags"] if tags is _UNSET else _recipe_tags(tags),
                          _recipe_defaults(w, start["defaults"], theme, aspect, voice))
    changed = [f for f in ("name", "prompt", "tags", "defaults") if after[f] != before[f]]
    if not changed:
        raise ToolFailed(f"That leaves the recipe {saved['name']!r} as it is.")
    _hold(w, {"recipe_ref": uuid.uuid4().hex, "op": "update", "recipe_id": rid,
              "before": before, "after": after, "fields": changed,
              "base_updated_at": saved["updated_at"], "state": "pending"}, held)
    return (f"Proposed changing the recipe {saved['name']!r}: {', '.join(changed)}. "
            f"{_SAVE_HINT}")


def _pending_create(w: Working, recipe: Any) -> Optional[Dict[str, Any]]:
    """The create proposed this turn that `recipe` names, when it names no saved one."""
    if not isinstance(recipe, str) or not recipe.strip():
        return None
    wanted = recipe.strip()
    if wanted in w.recipes or _name_taken(w, wanted, None):
        return None
    return next((p for p in w.recipe_proposals if p["op"] == "create"
                 and p["after"]["name"].lower() == wanted.lower()), None)

def web_search(w: Working, query: str) -> str:
    query = (query or "").strip()
    if not query:
        raise ToolFailed("Give a query to search the web for.")
    if w.web_search is None:
        raise ToolFailed("Web search is not available right now.")
    if w.web_searches >= w.max_web_searches:
        raise ToolFailed(f"That is {w.max_web_searches} web searches this request. "
                         "Work with what you have found.")
    w.web_searches += 1
    try:
        results = w.web_search(query)
    except Exception as exc:  # noqa: BLE001 - a failed search is information for the model
        raise ToolFailed(f"The web search failed: {exc}") from exc
    from gecko_suite_client import format_results

    text = format_results(results)
    return text[:MAX_WEB_CHARS] + ("\n[cut off]" if len(text) > MAX_WEB_CHARS else "")


_CANDIDATE_FIELDS = ("image_url", "page_url", "title", "thumbnail_url", "width", "height", "description")


def _candidate(hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A search hit as the spec keeps it: only the known fields, cut to the model's limits,
    so one long title from a site can't make the placeholder invalid."""
    url = hit.get("image_url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or len(url) > 2048:
        return None
    row: Dict[str, Any] = {}
    for name in _CANDIDATE_FIELDS:
        value = hit.get(name)
        if value in (None, ""):
            continue
        if name in ("width", "height"):
            if isinstance(value, int) and value > 0:
                row[name] = value
        elif isinstance(value, str):
            limit = {"title": 300, "description": 500}.get(name, 2048)
            if name in ("page_url", "thumbnail_url") and (
                    not value.startswith(("http://", "https://")) or len(value) > limit):
                continue
            row[name] = value[:limit]
    return row


def find_images(w: Working, query: str, segment_id: Optional[str] = None, use_as: str = "visual",
                label: Optional[str] = None) -> str:
    """Pictures from the web, left on a placeholder for the person to choose from.

    Never placed in the video directly: the person sees the candidates (and their source
    pages) in the editor and picks one, which files it in GAM and resolves the
    placeholder. That is the user's call, and it keeps the rule that the web is for
    reading: what the model chose is a shortlist, not a picture on screen.
    """
    query = (query or "").strip()
    if not query:
        raise ToolFailed("Say what the picture should show.")
    if w.image_search is None:
        raise ToolFailed("Searching the web for pictures is not available right now.")
    if w.image_searches >= w.max_image_searches:
        raise ToolFailed(f"That is {w.max_image_searches} picture searches this request. "
                         "Use search_assets or leave a placeholder with add_placeholder.")
    if use_as not in ("visual", "overlay", "background", "none"):
        raise ToolFailed('use_as is "visual", "overlay", "background" or "none".')
    if use_as in ("visual", "overlay") and not segment_id:
        raise ToolFailed('Say which segment the picture is for, or use_as "background" or "none".')
    if segment_id:
        w.index_of(segment_id)  # a bad id is said before the search is spent

    w.image_searches += 1
    try:
        hits = w.image_search(query)
    except Exception as exc:  # noqa: BLE001 - a failed search is information for the model
        raise ToolFailed(f"The picture search failed: {exc}") from exc
    candidates: List[Dict[str, Any]] = []
    seen: set = set()
    for c in (_candidate(h) for h in hits if isinstance(h, dict)):
        # The first listing of a picture wins: it is the engine's best-ranked, and the
        # one most likely to carry its page and description.
        if c and c["image_url"] not in seen:
            seen.add(c["image_url"])
            candidates.append(c)
    candidates = candidates[:MAX_WEB_CANDIDATES]
    if not candidates:
        return "No pictures found for that. Try other words, or search_assets."

    candidate = copy.deepcopy(w.data)
    assets = candidate.setdefault("assets", {})
    base = f"a_{_slug(label or query) or 'web'}"
    key, n = base, 2
    while key in assets:
        key, n = f"{base}_{n}", n + 1
    ref: Dict[str, Any] = {"from": "search", "query": query, "type": "image", "candidates": candidates}
    if label:
        ref["label"] = label
    assets[key] = ref
    where = "kept in the registry"
    if use_as == "background":
        style = candidate.setdefault("style", {})
        style["background"] = {**(style.get("background") or {}), "type": "image", "asset": key}
        where = "as the video's background"
    elif segment_id:
        segment = candidate["segments"][w.index_of(segment_id)]
        if use_as == "visual":
            segment["visual"] = {"asset": key}
            where = f"as the picture of {w.name_of(segment)}"
        elif use_as == "overlay":
            segment.setdefault("overlays", []).append(
                {"id": w.new_id("o_", w.all_overlay_ids()), "type": "image", "asset": key,
                 "position": "top-right", "scale_pct": 30})
            where = f"on screen over {w.name_of(segment)}"
    result = w.commit(candidate, f"Found {len(candidates)} pictures to choose from {where}: {query[:80]!r}")
    lines = []
    for i, c in enumerate(candidates, 1):
        size = f" {c['width']}x{c['height']}" if c.get("width") and c.get("height") else ""
        text = c.get("description") or c.get("title") or "(no description)"
        lines.append(f"[{i}]{size} {text[:200]}" + (f" ({c['page_url']})" if c.get("page_url") else ""))
    return (f"{result} Placeholder {key} holds them; the user chooses one in the editor, and "
            "until then the scene shows a slate. Tell them to choose; never say a picture is "
            "in place. The rights to these are unknown.\n" + "\n".join(lines))


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
              "sound you want. more_moments: how many other moments in that asset also "
              "matched; read_transcript shows them. Documents (PDF, Word, slides, "
              "spreadsheets, text) are searched by what is written in them: use type "
              "document, and a hit inside one carries page, the part it is on; "
              "read_document reads it.",
              {"type": "object", "properties": {
                  "query": _STR,
                  "type": {"type": "string", "enum": ["video", "image", "audio", "document"]},
                  "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_HITS}},
               "required": ["query"]}), search_assets),
    (ToolSpec("read_transcript",
              "What is said in a library video or recording, one sentence per line with its "
              "[start-end] seconds. Use it on candidate videos before choosing a clip, to find "
              "the passage that best makes the point. start/end read just that stretch; a long "
              "transcript comes in pages and says where to carry on.",
              {"type": "object", "properties": {"gam_id": _STR, "start": _NUM, "end": _NUM},
               "required": ["gam_id"]}), read_transcript),
    (ToolSpec("read_document",
              "The text of a document in the library (a PDF, Word file, slides, spreadsheet "
              "or text file), part by part, each headed [n] and its label (Page 3, Slide 7, "
              "Part 2). Use it whenever the person refers to a document, before saying what "
              "it says. start/end read parts n to m: a search hit's page_number, or the n "
              "of a part, is where to start. A long document comes in pages and says where "
              "to carry on. It informs the script; a document is never footage.",
              {"type": "object", "properties": {
                  "gam_id": _STR, "start": {"type": "integer", "minimum": 1},
                  "end": {"type": "integer", "minimum": 1}},
               "required": ["gam_id"]}), read_document),
    (ToolSpec("find_clips",
              "Read a whole library video's transcript, in a separate pass, and return the "
              "passages that best put across one idea, best scored, each with the trim to "
              "pass to set_visual, what is said and why it fits. Use it on each candidate "
              "video from search_assets before choosing a clip: it sees all of the video, "
              "where a search shows one moment. idea: what the scene needs said, in a "
              "sentence. count: passages wanted (1-5, default 3).",
              {"type": "object", "properties": {
                  "gam_id": _STR, "idea": _STR,
                  "count": {"type": "integer", "minimum": 1, "maximum": 5}},
               "required": ["gam_id", "idea"]}), find_clips),
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
              "you) or asset (an existing registry key). A video hit's said_at, grown to whole "
              "sentences, becomes the trim unless trim is given. motion and fit as in the spec.",
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
    (ToolSpec("set_theme",
              "Set the video's theme: one of the user's named looks (listed in the context), "
              "by name or id, whose style is added to every picture and clip generated for "
              "the video. Omit theme (or \"none\") to remove it.",
              {"type": "object", "properties": {"theme": _STR}}), set_theme),
    (ToolSpec("create_theme",
              "Add a new theme to the user's list. name: a short name. prompt: the look "
              "it adds after every picture and clip prompt: style, medium, light, colour "
              "palette; never a subject. It is saved at once, whatever happens to the "
              "proposal. use: true also makes it this video's theme; only when the user "
              "wants this video in that look, or you are drafting a video in it. Only "
              "when the user asks for a theme, or wants a look none of theirs has.",
              {"type": "object", "properties": {"name": _STR, "prompt": _STR,
                                                "use": {"type": "boolean"}},
               "required": ["name", "prompt"]}), create_theme),
    (ToolSpec("update_theme",
              "Change one of the user's themes (by name or id): its name, its prompt (the "
              "look it adds), or make_default (true: new projects start with it; false: "
              "no default). Saved at once, and restyles every project using it from then "
              "on. Only when the user asks for that theme to change.",
              {"type": "object", "properties": {"theme": _STR, "name": _STR, "prompt": _STR,
                                                "make_default": {"type": "boolean"}},
               "required": ["theme"]}), update_theme),
    (ToolSpec("delete_theme",
              "Delete one of the user's themes (by name or id), at once and for good. "
              "Projects using it generate without a theme afterwards. Only when the user "
              "asks for that theme to be deleted.",
              {"type": "object", "properties": {"theme": _STR}, "required": ["theme"]}),
     delete_theme),
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
    (ToolSpec("propose_note",
              "Propose a new note in Gecko Notes, the user's notes app: the script, a shot "
              "list, research, a summary of footage. Write it in Markdown. Link a GAM asset "
              "as [Name](/a/<gam_id>), which becomes a link to it in the library. Nothing "
              "is written until the user presses the note's button; it then lands in their "
              "\"From Video Creator\" folder, or the folder they named. It does not change "
              "the video. Only when the user asks for a note.",
              {"type": "object", "properties": {
                  "title": _STR, "markdown": _STR,
                  "folder": {"type": "string",
                             "description": "Only when the user names a folder."}},
               "required": ["title", "markdown"]}), propose_note),
    (ToolSpec("list_recipes",
              "The user's recipes: saved requests with {{inputs}} they run to make or change "
              "a video. Each has its id, name, tags, inputs, defaults and the start of its "
              "prompt. tag: only those with that tag.",
              {"type": "object", "properties": {"tag": _STR}}), list_recipes),
    (ToolSpec("get_recipe", "One of the user's recipes whole, by name or id: read it before "
              "proposing a change to its prompt.",
              {"type": "object", "properties": {"recipe": _STR}, "required": ["recipe"]}),
     get_recipe),
    (ToolSpec("propose_recipe",
              "Propose a change to the user's recipe list: a new recipe (op create, with name "
              "and prompt), a change to one (op update: recipe, and only the fields that "
              "change; null clears theme, aspect or voice), or deleting one (op delete: "
              "recipe). Nothing is saved until the user presses the button on your reply. It "
              "does not change the video. Only when the user asks about recipes.",
              {"type": "object", "properties": {
                  "op": {"type": "string", "enum": list(RECIPE_OPS)},
                  "recipe": {"type": "string",
                             "description": "update and delete: its name or id"},
                  "name": _STR,
                  "prompt": {"type": "string",
                             "description": "The whole request, standing alone. {{name}} for "
                             "what changes between runs; {{title}}, {{date}} fill themselves."},
                  "tags": {"type": "array", "items": _STR},
                  "theme": {"type": ["string", "null"],
                            "description": "A theme's name or id for videos made from it"},
                  "aspect": {"type": ["string", "null"], "enum": ["16:9", "9:16", "1:1", None]},
                  "voice": {"type": ["object", "null"], "properties": {
                      "provider": _STR, "voice": _STR, "speed": _NUM,
                      "expressivity": {"type": "integer"}}}},
               "required": ["op"]}), propose_recipe),
    (ToolSpec("web_search", "Search the web, for what the library cannot say: a fact for the "
              "script, who someone is, when something happened. Returns titles, links and short "
              "passages. Say where a fact came from; it is not a way to find footage (use "
              "search_assets).",
              {"type": "object", "properties": {"query": _STR}, "required": ["query"]}),
     web_search),
    (ToolSpec("find_images",
              "Search the web for pictures (a background, a segment's picture, an overlay) and "
              "leave the best ones on a placeholder for the user to choose from. Nothing goes on "
              "screen until they choose, and their choice is filed in the library. Search the "
              "library (search_assets) first; use this for what it doesn't have. use_as: "
              "visual (the segment's picture), overlay (over the segment), background (the "
              "whole video's), none (kept in the registry). Describe what should be seen.",
              {"type": "object", "properties": {
                  "query": _STR, "segment_id": _STR,
                  "use_as": {"type": "string", "enum": ["visual", "overlay", "background", "none"]},
                  "label": _STR},
               "required": ["query"]}), find_images),
    (ToolSpec("estimate", "How long the video runs, its narration length, and what would "
              "stop a full render.", {"type": "object", "properties": {}}), run_estimate),
]

SPECS = [spec for spec, _ in TOOLS]
_HANDLERS = {spec.name: handler for spec, handler in TOOLS}

# Read-only tools, which neither change the video nor count as an edit in the steps.
READS = {"get_spec", "search_assets", "read_transcript", "read_document", "find_clips",
         "get_asset", "estimate", "web_search", "list_recipes", "get_recipe"}


def specs_for(w: Working) -> List[ToolSpec]:
    """The tools a turn is offered: all of them, except the web (pages or pictures) where
    there is none, and
    notes where there is no token to make one with."""
    return [s for s in SPECS
            if (s.name != "web_search" or w.web_search is not None)
            and (s.name != "find_images" or w.image_search is not None)
            and (s.name != "propose_note" or w.can_note)]


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


def plan(w: Working, call: ToolCall) -> "ToolResult | ClipJob":
    """`execute`, except that a find_clips call needing the picker comes back as its job,
    for the loop to run with the round's others. Never raises, as `execute` doesn't."""
    if call.name != "find_clips" or call.parse_error:
        return execute(w, call)
    try:
        planned = plan_clips(w, **call.arguments)
    except ToolFailed as exc:
        return ToolResult(call.id, str(exc), is_error=True)
    except TypeError as exc:
        return ToolResult(call.id, f"Wrong arguments for {call.name}: {exc}", is_error=True)
    return ToolResult(call.id, planned) if isinstance(planned, str) else planned
