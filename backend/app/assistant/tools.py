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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.assistant import clips
from app.gam.client import GamClient, GamError
from app.providers.base import ProviderError, ToolCall, ToolResult, ToolSpec
from app.schemas_gam import GamTranscript
from app.render.estimate import estimate
from app.services import note_media as note_files
from app.services.themes import theme_id_of
from app.spec.validation import SpecIssue, parse_spec

# A found moment is padded so a cut doesn't clip a word: the editor's `momentTrim`.
MOMENT_PAD = 0.5
DEFAULT_MOMENT_SECONDS = 5.0
MAX_SEARCH_HITS = 12
# A transcript is read in pages of about 8k tokens. Every result stays in the turn's
# conversation and is sent again each round, so an hour of speech in one call would cost
# far more than reading the stretch around what was found.
MAX_TRANSCRIPT_CHARS = 30_000
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
    wanted = theme.strip()
    found = wanted if wanted in w.themes else next(
        (tid for tid, t in w.themes.items() if t["name"].strip().lower() == wanted.lower()),
        None)
    if found is None:
        names = ", ".join(repr(t["name"]) for t in w.themes.values()) or "none; the user " \
            "hasn't made any (they are made in Settings)"
        raise ToolFailed(f"No theme {wanted!r}. The themes are: {names}.")
    style["theme"] = found
    return w.commit(candidate, f"Set the theme to {w.themes[found]['name']!r}")


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
              "matched; read_transcript shows them.",
              {"type": "object", "properties": {
                  "query": _STR, "type": {"type": "string", "enum": ["video", "image", "audio"]},
                  "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_HITS}},
               "required": ["query"]}), search_assets),
    (ToolSpec("read_transcript",
              "What is said in a library video or recording, one sentence per line with its "
              "[start-end] seconds. Use it on candidate videos before choosing a clip, to find "
              "the passage that best makes the point. start/end read just that stretch; a long "
              "transcript comes in pages and says where to carry on.",
              {"type": "object", "properties": {"gam_id": _STR, "start": _NUM, "end": _NUM},
               "required": ["gam_id"]}), read_transcript),
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
READS = {"get_spec", "search_assets", "read_transcript", "find_clips", "get_asset",
         "estimate"}


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
