# Gecko Video Creator — Plan of Attack

## Context

GVC is the third app in the Gecko Suite, beside
[gecko-notes](https://github.com/davior/gecko-notes) (scripts, and the identity provider)
and [GAM](https://github.com/davior/gam) (the media library). Its job: **one place to put
a narrated video presentation together quickly, scene by scene**, where an AI drafts the
whole thing from a prompt and you then tweak whichever parts you want.

A video is a JSON document, the **VideoSpec**. Its draft schema, its reasoning and a full
worked example are in gecko-notes'
[`docs/gecko-video-creator.md`](https://github.com/davior/gecko-notes/blob/main/docs/gecko-video-creator.md)
(called *the Notes spec doc* below), and its canonical Pydantic model is
[`backend/app/video/spec.py`](https://github.com/davior/gecko-notes/blob/main/backend/app/video/spec.py)
there. Read §4–§6 of that doc before touching the schema. This document doesn't repeat
it. It records where things stand, what the goal adds to that design, and the order to
build in.

### What the goal asks for

In the user's words, condensed:

1. **Prompt an AI to write the script**: from scratch, from GAM assets, or from a note.
   The output is a spec complete enough to render straight away.
2. **Scene by scene**: titles, on-screen text, narration (text to speech), and cuts of
   video from GAM.
3. **Find clips by what is said in them**: "find where people talk about *X*", and
   bring those moments into the script as trimmed clips.
4. **Change the soundtrack through the video**, not one bed for the whole thing.
5. **A default transition between scenes, overridable per scene.**
6. **Ken Burns defined per scene**, including *which part* of a picture it moves over.
7. **Render immediately, tweak later.** The AI's draft is a starting point, not a
   take-it-or-leave-it.
8. **It stands by itself.** A video can be built entirely by hand, scene by scene. A
   note can be pushed in from Notes, after which it's a GVC project like any other and
   is managed only in GVC (D3).

## Where things stand (2026-10-16)

Read from the code, not from READMEs.

**gecko-notes: Phase 0 is done.** Every Notes video render now goes through a VideoSpec:
`importer.py` (note → spec), `compiler.py` (spec → the `Shot`s and `RenderOptions` the
old renderer takes) and parity tests holding the output byte-for-byte to the pre-spec
walk. `POST /api/video/spec` returns the spec for a note. So the schema is proven
against a renderer that works.

But the compiler **refuses** everything the old renderer can't do
(`compiler._refuse_unsupported`), and that list is most of this goal:

| Goal | In the schema | Renders in Notes today |
|---|---|---|
| Several soundtracks, changing through the video | ✅ `audio_tracks[]`, anchored to segments/beats, with fades and crossfades | ❌ one music bed, first content segment to last |
| Default transition + per-scene override | ✅ `style.transition` + `segment.transition_in` | ❌ one global style; per segment, only a straight cut |
| Ken Burns per scene | 🟡 `visual.motion` (preset effect + amount) | ❌ global only |
| Ken Burns over a chosen *part* of the picture | ❌ not modelled (see S1 below) | ❌ |
| Trimmed clips (a moment out of a long video) | ✅ `visual.trim` | ❌ clips play whole |
| GAM assets, `search` / `generate` placeholders | ✅ `AssetRef` union | ❌ note media only |
| Lower thirds, timed text, image overlays | ✅ `overlays[]` | ❌ quote/code only, as their own shot |
| Per-scene voice | ✅ `narration.voice` | ❌ |
| AI writes the spec from a prompt | ❌ the design is note-first (see S2 below) | ❌ |

**GAM: the media side is largely there.**
- Upload, URL import (YouTube and ~1,800 yt-dlp sites, with captions as transcripts),
  Deepgram transcription, tags, AI descriptions, attribution (M10), clips (M7), and
  fal.ai generation (M8, built but never run against a live fal host).
- **Search** (`GET /api/search`) is hybrid keyword (FTS5) + semantic (embeddings) over
  transcripts, and a hit inside audio or video carries `start_time` and `segment_id`.
  That is exactly the "find where people talk about *X*" primitive.
- Missing, as far as GVC is concerned:
  - **No `end_time` on a hit.** GVC needs an out point to cut a clip. The transcript
    segment has one; the API doesn't return it (see GAM changes below).
  - **M5's acceptance run was never done**, so nobody has yet confirmed search finds
    the right second on a real library. Semantic search also needs an embedding
    provider configured, or only the keyword half runs (the response says so via
    `semantic: false`).
  - **M9 (the GVC surface: picker, documented read API) is not started.** It was
    deliberately left waiting for GVC.
  - `origin_project_id` on `Asset`, to file a finished render back as `gvc_export`,
    is planned and not migrated.

**GVC: this repository is empty.**

## Decisions taken

### D1. GVC renders specs natively; it does not compile back to `Shot`s

The Notes compiler maps a spec onto the old renderer's flat shot list and one global
options object. That mapping is why it refuses multiple tracks, per-scene transitions
and per-scene motion: the target can't express them. GVC copies the low-level pieces
(`ffmpeg.py`, `compose.py`, `narration.py`, `pause_markup.py`, `shot_cache.py`) and
writes the compile step the Notes spec doc §5.8 describes, **spec → absolute timeline**,
with a renderer that reads that timeline. The ffmpeg building blocks already exist:
- `build_xfade_command` already supports a per-join exception (a straight cut), so a
  per-join style and duration is a generalisation, not a new mechanism.
- `build_music_command` already ducks one bed under narration with `sidechaincompress`.
  N tracks becomes N `adelay`/`atrim`/`afade`/`volume` chains into one `amix`.
- `kenburns_chain` already drives `zoompan` with an explicit sweep. A start/end
  rectangle is a different pair of endpoints for that sweep.

Rejected: building GVC Phase 1 as "parity with Notes first" (the Notes spec doc §10,
Phase 1). Parity is already proven in Notes, and spending the first milestone
reproducing a renderer whose limits are the problem defers everything this goal is for.
The parity tests stay in Notes, where the oracle lives.

### D2. The AI drafts a whole spec; it edits through operations

The Notes spec doc says the AI never rewrites the document and only emits small
operations (principle 6). That rule is right for **editing** a video that exists. It
doesn't fit **drafting** one from a prompt, where there is nothing to patch and
forty `add_segment` calls are slower, costlier and harder for a model to keep coherent
than one document. So:
- **Draft:** the model returns one VideoSpec as structured output. Pydantic validates
  it; on failure the validation errors go back to the model for one repair round. The
  draft is version 1 of the project, so it can be undone like any edit.
- **Edit:** the §8.2 operations, addressed by id (open decision 14 there), staged as
  suggestions you accept or reject.

The AI is given GAM search as a tool while drafting. Anything it can't find, it leaves
as a `search` or `generate` placeholder rather than inventing an asset id. A preview
renders placeholders as labelled slates, so a draft is watchable before every shot
exists.

### D3. GVC stands by itself: three ways in, one project

GVC is a complete tool on its own. There are three ways to start a video, and all of
them end as an ordinary VideoSpec that GVC owns:

- **Blank, by hand.** A new project starts with a title card and one empty scene, and
  you build it scene by scene: the picture, the words, the transition into it, how
  the camera moves, where the music changes. No AI and no note are involved.
- **From a prompt**, optionally with GAM assets to start from. The AI drafts the whole
  spec (D2).
- **Pushed from Notes.** Notes' "Make video" button builds a spec from the note (Notes
  already does this: `POST /api/video/spec`), POSTs it to GVC's
  `POST /api/projects/import` with the user's token, and opens the new project in GVC.
  **It's a one-way hand-off.** From then on the project lives in GVC and is edited only
  there, and nothing flows back to the note.

Nothing after creation knows or cares which way a project came in. Consequences:
- The Notes spec doc's re-sync (its §9.1) is dropped, and its open decision 7 is
  decided as **never**.
- `source: { kind: "note", … }` is provenance only ("pushed from note X on date Y"),
  shown in the UI and never used to rewrite anything. `Beat.block_id` and
  `segment.source.block_ids` stay in the schema for the same reason, and nothing
  reads them.
- The Notes media a pushed spec refers to (`from: "notes"` URLs) is copied into GAM
  when the project is imported, so afterwards the project doesn't depend on the note
  either. A pushed project says how many files are still in the note, and "Copy into
  GAM" (`POST /api/projects/{id}/copy-note-media`) moves them, replacing each ref
  under the same key so nothing that pointed at it changes. Files that fail stay as
  they were, to retry.
- **The one remaining runtime tie to Notes is login.** GVC verifies the JWT Notes
  issues (suite SSO), as GAM does, and has no accounts of its own. If Notes is down,
  nobody can sign in anew, but everything else in GVC keeps working.

That's also why the **editor comes before AI drafting** in the milestones. Building by
hand is a first-class way to use GVC, not a fallback for when the AI gets it wrong. It's
also where every AI draft gets fixed.

### D4. Same stack and conventions as GAM

FastAPI + SQLModel (SQLite) + Alembic, React 18 + Vite + TypeScript + Zustand +
Tailwind, Docker Compose + Nginx, Python 3.13. GVC starts from GAM's skeleton
(`config.py`, `clock.py`, `CurrentUser` with a shadow user on the Notes JWT's `sub`,
three-job CI), not from Notes'. GAM's skeleton is the one that already fixed Notes'
module-scope `os.getenv` and `try: ALTER TABLE` habits. AI providers, usage events and
pricing come from GAM's M6 (`providers/`, `usage/`), which already covers Anthropic,
OpenAI, DeepSeek and Ollama.

Dev ports: **8002** (backend) and **5175** (frontend). Notes uses 8000/5173, GAM
8001/5174, and all three run at once.

## Schema changes this goal needs

These change the VideoSpec. They are made in GVC's copy of `spec.py` in M0,
when the schema moves here (the Notes spec doc §10). Notes never renders them, and its
compiler keeps refusing anything it doesn't know.

### S1. Ken Burns framing: start and end rectangles

Today `Motion` is a preset (`zoom_in`, `pan_left`, …) and an `amount`. A preset can't
say "start on the whole map, end on the oasis in the lower left". Add an explicit path:

```ts
interface Motion {
  effect: "none" | "zoom_in" | "zoom_out" | "pan_left" | "pan_right"
        | "pan_up" | "pan_down" | "alternate" | "path";
  amount?: number;                 // presets only
  from?: Frame;                    // effect "path" only: required
  to?: Frame;
  ease?: "linear" | "in_out";      // "in_out" (default) for path, "linear" matches today's presets
}

interface Frame {                  // a crop of the source picture, as fractions of it
  x: number; y: number;            // top-left, 0–1
  w: number;                       // 0–1. Height follows from the output aspect,
}                                  //   so a frame can never distort the picture
```

- **Fractions, not pixels**, so a frame survives replacing the picture with a larger
  copy, and an AI can say "the left third" without knowing the resolution.
- **`w` only.** Storing `h` too invites a crop whose aspect doesn't match the output,
  which `zoompan` would stretch.
- **The presets stay**, as shorthand for the common moves and for `alternate` at
  project level. Each preset is defined as a `from`/`to` pair in the compiler, so
  there's one code path.
- The editor UI sets a frame by dragging a box over the picture. An AI picking a
  region from an image it can see (a vision-capable provider: GAM's
  `supports_images` flag) is a later nicety. Text-only models stick to presets.

### S2. Where a spec came from: note, assets or brief

`source` is note-only today. Make it a union, so a spec records what it was drafted
from and what to re-sync against:

```ts
source?:
  | { kind: "note"; note_id: string; note_version_id?: string;
      imported_at?: string; selection?: boolean }
  | { kind: "brief"; prompt: string; asset_ids?: string[];   // GAM assets it was
      drafted_at: string; provider?: string; model?: string } //   given to start from
```

Both are provenance only (D3): GVC never re-reads the note or re-runs the brief on its
own. A brief keeps its prompt so you can see later what was asked for, and re-draft on
request. A project made by hand has no `source`.

### S3. `search` placeholders that resolve to a moment

`{ from: "search", query }` resolves to an asset. To pull "where people talk about
*X*" into a scene, it needs to resolve to a **moment** with a length:

```ts
| { from: "search"; query: string; type?: "image" | "video" | "audio";
    moment?: { min?: number; max?: number };   // seconds; present = cut a clip
    status: "unresolved" | "resolved";
    result?: { from: "gam"; id: string; in?: number; out?: number } }
```

Resolving it takes the GAM hit's `start_time` and its transcript segment's end,
widened to `min` / shrunk to `max`, and writes them as `in`/`out`. The segment that
uses the asset gets them as `visual.trim`. A `clip` segment (sound on, no narration)
plays the person saying it. A muted `scene` uses it as b-roll under narration.

### S4. Nothing new needed for soundtracks or transitions

Both are already in the schema. Soundtrack changes are several `audio_tracks`, each
anchored to the segments it spans, and a crossfade is an overlap with matching fades
(the Notes spec doc §5.4, §6). A default transition with per-scene overrides is
`style.transition` plus `segment.transition_in`. The work is in the renderer (D1), not
the schema. One schema question remains open: whether `transition_in` and `motion`
override field by field or as a whole object (the Notes spec doc, open decision 13).
This plan takes **field by field**, so `{ "transition_in": { "style": "dissolve" } }`
keeps the project's duration, because that is what the AI and the editor will both
expect.

## Changes needed in GAM

Specified here, applied in GAM's repository, not from this one.

| | Change | Why |
|---|---|---|
| GAM-1 | `end_time` on `SearchHit`, from the transcript segment. **Done: [davior/gam#36](https://github.com/davior/gam/pull/36).** GVC also works without it, sizing a moment as start + 5 s | S3: a moment needs an out point |
| GAM-2 | Run M5's acceptance on a real library; document that semantic search needs an embedding provider | "Find where people talk about *X*" is the feature most of this goal rests on, and it has never been checked end to end |
| GAM-3 | `origin_project_id` / `origin_reference_id` on `Asset` (migration) + upload with `source: "gvc_export"` | Filing renders back into the library |
| GAM-4 | M9: documented read API, `/picker?embed=1` with `postMessage({ assetId, inPoint, outPoint })` | Picking assets and moments by hand in the editor |
| GAM-5 | `CORS_ORIGIN` / CSP for `gvc.geckopico.com`, only where GVC's browser code calls GAM directly | Server-side calls with a Bearer token need neither |

GAM-1 and GAM-2 come first. They're small, and M1 below depends on them.

## Changes needed in Notes

| | Change | Why |
|---|---|---|
| GN-V1 | "Make video" posts the spec from `POST /api/video/spec` to GVC's `POST /api/projects/import` and opens the returned project | The one-way push (D3) |
| ~~GN-V2~~ | **Not needed.** Notes serves `/media/*` with no authentication at all (`gecko-notes/backend/app/main.py`), so GVC's server fetches a pushed note's files directly. Worth knowing for its own sake: anyone holding a note's media URL can fetch it, which is Notes' existing behaviour, not something GVC adds | |
| GN-V3 | Once GVC renders (M2): Notes' own render pipeline is retired (the Notes spec doc §10, Phase 4) | One renderer, not two |

## Milestones

Each milestone ends with something you can use, not just with code merged.

| | Milestone | Scope | Done when |
|---|---|---|---|
| **M0** | **Genesis** | Skeleton from GAM: `config.py`, `clock.py`, Alembic, shadow-user auth on the Notes JWT, `/api/health`, Dockerfiles (backend with ffmpeg), compose, nginx, CI. `Project` (current spec as JSON) and `ProjectVersion` (snapshot, author, message). Spec Pydantic model copied from Notes with S1–S3 applied, `0.1 → 0.2` migration on load. Projects API: blank project (title card + one empty scene), paste a spec, `POST /api/projects/import` for a Notes push, versions and revert, validation with errors by path. React shell: project list, a plain scene list (add, reorder, delete, edit narration), a JSON tab with live validation, version history. | You can sign in with your Notes account, make a video's structure by hand, paste the Notes spec doc's §6 example and see it validate (or see exactly why not), and import a spec Notes produced |
| **M1** | **GAM as the library** | GAM-1 applied (gam#36). GVC's server calls GAM as the signed-in user by forwarding their own Notes token, so GAM's ownership checks hold and no service account exists. Search GAM from a scene: results with transcript snippets and the moment's time; picking a hit places it as muted b-roll or as a clip with its own sound, trimmed to what was said (padded, and sized by a placeholder's `moment`). `search` placeholders resolved the same way. Thumbnails and names looked up per page load, since GAM's signed URLs expire, and loaded straight from GAM (CSP `img-src`/`media-src`). A pushed note's media copied into GAM (D3). The byte cache keyed on asset id and checksum moved to M2: nothing reads media bytes until the renderer does. | A scene's footage is found by what is said in it ("where people talk about *X*") and lands in the spec as a trimmed GAM clip |
| **M2** | **Native renderer** | Engine copied from Notes (D1). The compile step from the Notes spec doc §5.8, plus S1 framing. Renders: per-join transitions with the project default, per-scene motion and framing, N audio tracks with fades, crossfades and ducking, trims, card/scene/clip. All media from GAM (M1), its bytes fetched through signed URLs into a local cache keyed on asset id and checksum. Placeholder slates. Preview (480p) and full render as jobs. Download, and file the render back to GAM (GAM-3). Credits from GAM attribution. TTS through Notes' `POST /api/settings/speech/tts`, so voices and keys stay in one place (open decision 3). | A spec with two music tracks crossfading at a scene cut, a dissolve into one scene, and a Ken Burns path over a chosen part of a picture renders correctly |
| **M3** | **Editor** | The M0 scene list grows into the storyboard: a card per segment (thumbnail, label, first line), lanes for audio tracks and overlays against the segments, a per-scene panel (visual, trim, transition, motion with a drag-a-box framing tool, voice), a project defaults panel. Sliders take their ranges from the schema (the Notes spec doc, open decision 12). Undo/redo over `ProjectVersion`. | You can build and fix a whole video by hand without opening the JSON tab |
| **M4** | **AI drafting** | Providers copied from GAM's M6. "New video from a prompt": brief → spec (D2) with GAM search as a tool, and placeholders for gaps, with one repair round. Also from selected GAM assets. Cost estimate before running, usage recorded. | "Make a 3-minute video about *X* using clips where people talk about it" produces a spec that previews immediately |
| **M5** | **AI editing** | The Notes spec doc §8.2 operations, addressed by id. Chat beside the storyboard. Suggestions staged and accepted one by one. Generate placeholders sent to GAM's M8. | "Change the music after the second chapter to something calmer, and dissolve into the last scene" becomes reviewed, applied edits |
| **M6** | **Notes hands over** | GN-V1 to GN-V3: "Make video" in Notes pushes to GVC, and Notes' render pipeline is retired (the Notes spec doc §10, Phase 4). | No render code left in Notes |

**M1 before M2** is the user's call: real media from GAM from the first render, with
no throwaway upload path inside GVC. It also puts GAM's search to work early, where
the riskiest dependency of this goal ("find where people talk about *X*") gets checked
on a real library before anything is built on it. **M3 before M4** is deliberate (D3):
building by hand is a first-class way to use GVC, and an AI draft is only "render now,
tweak later" if there's somewhere to tweak it.

## Open decisions

The Notes spec doc §12 lists fourteen. These are the ones this plan needs answered, in
the order it hits them:

1. **Repo default branch.** This repository had no commits, so the first push created
   its only branch. Create `main` from it before M0's first PR, so CI's
   `pull_request: branches: [main]` has a target.
2. **Spec version.** S1–S3 change the schema. Bump to `"0.2"` with a load-time
   migration from `0.1` (Notes' `POST /api/video/spec` emits `0.1`), the JSON
   equivalent of an Alembic revision (the Notes spec doc, open decision 8).
3. **Who owns TTS.** M2 calls Notes for speech, which keeps one set of voices and keys
   but means a Notes outage stops renders. The alternative is copying the TTS core and
   giving GVC its own keys.
4. **Default model for drafting.** The draft is one long structured-output call, which
   suits the most capable model a provider offers. Edits are short and can go to a
   cheaper one. GAM's provider settings already allow a choice per task.
