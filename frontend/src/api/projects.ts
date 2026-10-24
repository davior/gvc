import client from '@/api/client'

/**
 * Projects and the VideoSpec documents they hold.
 *
 * The spec types are deliberately partial: they name what the frontend reads and
 * edits, and carry everything else through untouched (`[key: string]: unknown`). The
 * backend's Pydantic model is the definition, and `/spec/schema` serves it; a full
 * hand-written copy here would be a second definition free to drift from the first.
 */

export interface Beat {
  id: string
  text: string
  [key: string]: unknown
}

export interface Card {
  variant: 'title' | 'chapter'
  title: string
  subtitle?: string
}

export interface Trim {
  in: number
  out?: number
}

/** A crop of a picture, as fractions of it. Its height follows from the output's
 *  aspect ratio, so there is no `h`. */
export interface Frame {
  x: number
  y: number
  w: number
}

export interface Motion {
  effect: string
  amount?: number
  from?: Frame
  to?: Frame
  ease?: 'linear' | 'in_out'
}

export interface Visual {
  asset: string
  trim?: Trim
  audio?: 'mute' | 'play'
  loop?: boolean
  /** A clip's sound, in dB from the narration's loudness it is matched to. */
  volume_db?: number
  fit?: string
  motion?: Motion
  [key: string]: unknown
}

export type Anchor =
  | 'video_start'
  | 'video_end'
  | { segment?: string; beat?: string; edge: 'start' | 'end'; offset?: number }

export interface AudioTrack {
  id: string
  kind?: 'music' | 'sfx' | 'voiceover'
  asset: string
  start: Anchor
  /** Absent: play once to its natural end. */
  end?: Anchor
  trim?: Trim
  loop?: boolean
  volume?: number
  duck_under_narration?: boolean
  /** While a clip plays its own sound. Absent: as under narration. */
  during_clips?: 'mute' | 'play'
  fade_in?: number
  fade_out?: number
  [key: string]: unknown
}

/** An entry in the spec's asset registry. Only the fields the editor reads are named. */
export type AssetRef =
  | { from: 'gam'; id: string; type?: string; label?: string }
  | { from: 'notes'; url: string; type: string; label?: string }
  | {
      from: 'generate'
      type: 'image' | 'video' | 'music' | 'sfx' | string
      prompt: string
      status?: 'pending' | 'running' | 'ready' | 'failed'
      /** What was made, once one is chosen; other outputs stay with the generation. */
      result?: { from: 'gam'; id: string }
      /** Registry keys of the pictures a clip is made from. */
      base_assets?: string[]
      label?: string
      [key: string]: unknown
    }
  | {
      from: 'search'
      query: string
      type?: string
      moment?: { min?: number; max?: number }
      status?: 'unresolved' | 'resolved'
      result?: { from: 'gam'; id: string; in?: number; out?: number }
      label?: string
    }

export type Position =
  'top-left' | 'top-right' | 'center' | 'bottom-left' | 'bottom-right'

export type WaveMode = 'line' | 'p2p' | 'cline' | 'point'
export type WavePosition = 'top' | 'center' | 'bottom'

/** When an overlay shows. Absent on the overlay: its whole scene. */
export interface Span {
  from: Anchor
  to: Anchor
}

interface OverlayBase {
  id: string
  show?: Span
  /** Seconds each way; absent: a short default. */
  fade?: number
  [key: string]: unknown
}

export type Overlay =
  | (OverlayBase & { type: 'quote'; text: string; attribution?: string })
  | (OverlayBase & { type: 'code'; text: string; language?: string })
  | (OverlayBase & {
      type: 'text'
      text: string
      position?: Position
      size_pct?: number
      color?: string
    })
  | (OverlayBase & { type: 'lower_third'; title: string; subtitle?: string })
  | (OverlayBase & {
      type: 'image'
      asset: string
      position?: Position
      scale_pct?: number
      opacity?: number
    })
  | (OverlayBase & {
      type: 'waveform'
      mode?: WaveMode
      color?: string
      opacity?: number
      position?: WavePosition
      height_pct?: number
      scrim?: number
    })

/** The end credits. Lines come from each GAM asset's credit, then `extra`. */
export interface Credits {
  auto?: boolean
  card?: boolean
  description?: boolean
  extra?: string[]
}

export interface Segment {
  id: string
  kind: 'scene' | 'card' | 'clip'
  role?: 'title' | 'intro' | 'outro'
  label?: string
  chapter?: string
  card?: Card
  visual?: Visual
  narration?: { beats: Beat[]; [key: string]: unknown }
  transition_in?: { style?: string; duration?: number }
  overlays?: Overlay[]
  /** Seconds: `fixed` sets the scene's length, `min` floors one that follows narration. */
  duration?: { min?: number; fixed?: number }
  [key: string]: unknown
}

export interface VideoSpec {
  spec_version?: string
  id?: string
  title: string
  source?: { kind: 'note' | 'brief'; [key: string]: unknown }
  assets?: Record<string, AssetRef>
  segments: Segment[]
  audio_tracks?: AudioTrack[]
  credits?: Credits | null
  output?: { aspect?: '16:9' | '9:16' | '1:1'; [key: string]: unknown }
  style?: {
    transition?: { style?: string; duration?: number }
    motion?: Motion
    [key: string]: unknown
  }
  [key: string]: unknown
}

export type Origin = 'blank' | 'pasted' | 'note' | 'brief'

export interface ProjectSummary {
  id: string
  title: string
  origin: Origin
  version: number
  created_at: string
  updated_at: string
}

export interface Project extends ProjectSummary {
  spec: VideoSpec
  /** Files still inside the note this was pushed from; copied to GAM from M1. */
  pending_note_media: number
}

export interface Version {
  id: string
  seq: number
  author: 'user' | 'ai'
  message: string
  reverted_from: string | null
  created_at: string
}

/** One problem with a spec, at a path into it: `['segments', 2, 'visual', 'asset']`. */
export interface SpecIssue {
  path: (string | number)[]
  message: string
}

export interface Validation {
  valid: boolean
  issues: SpecIssue[]
  spec: VideoSpec | null
}

export interface NoteMediaCopy {
  project: Project
  copied: string[]
  failed: { key: string; message: string }[]
}

interface DataResponse<T> {
  data: T
}

interface ListResponse<T> {
  data: T[]
  total: number
  limit: number
  offset: number
}

export const projectsApi = {
  list(): Promise<ListResponse<ProjectSummary>> {
    return client.get<ListResponse<ProjectSummary>>('/projects').then((r) => r.data)
  },

  /** A blank project to build by hand. */
  create(title: string): Promise<Project> {
    return client
      .post<DataResponse<Project>>('/projects', { title })
      .then((r) => r.data.data)
  },

  /** A project started from a pasted spec. A 422 carries `detail.issues`. */
  createFromSpec(spec: unknown): Promise<Project> {
    return client
      .post<DataResponse<Project>>('/projects', { spec })
      .then((r) => r.data.data)
  },

  get(id: string): Promise<Project> {
    return client.get<DataResponse<Project>>(`/projects/${id}`).then((r) => r.data.data)
  },

  save(id: string, spec: VideoSpec, message = ''): Promise<Project> {
    return client
      .put<DataResponse<Project>>(`/projects/${id}`, { spec, message })
      .then((r) => r.data.data)
  },

  remove(id: string): Promise<void> {
    return client.delete(`/projects/${id}`).then(() => undefined)
  },

  versions(id: string): Promise<ListResponse<Version>> {
    return client
      .get<ListResponse<Version>>(`/projects/${id}/versions`)
      .then((r) => r.data)
  },

  revert(id: string, versionId: string): Promise<Project> {
    return client
      .post<DataResponse<Project>>(`/projects/${id}/revert/${versionId}`)
      .then((r) => r.data.data)
  },

  /** Move a pushed note's files into GAM; failures stay in the note, to retry. */
  copyNoteMedia(id: string): Promise<NoteMediaCopy> {
    return client
      .post<DataResponse<NoteMediaCopy>>(`/projects/${id}/copy-note-media`)
      .then((r) => r.data.data)
  },

  /** Always resolves for a reachable server: an invalid spec is an answer, not an error. */
  validate(spec: unknown): Promise<Validation> {
    return client
      .post<DataResponse<Validation>>('/spec/validate', spec)
      .then((r) => r.data.data)
  },
}

/** The issues a 422 `invalid_spec` carries, or none. */
export function specIssuesOf(error: unknown): SpecIssue[] {
  const detail = (
    error as {
      response?: { data?: { detail?: { code?: string; issues?: SpecIssue[] } } }
    }
  )?.response?.data?.detail
  return detail?.code === 'invalid_spec' && Array.isArray(detail.issues)
    ? detail.issues
    : []
}

/** `segments[2].visual.asset`, the way a person reads a path into JSON. */
export function formatPath(path: SpecIssue['path']): string {
  if (path.length === 0) return '(the whole spec)'
  return path
    .map((part, i) =>
      typeof part === 'number' ? `[${part}]` : i === 0 ? part : `.${part}`
    )
    .join('')
}
