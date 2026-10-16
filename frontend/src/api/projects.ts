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

export interface Segment {
  id: string
  kind: 'scene' | 'card' | 'clip'
  role?: 'title' | 'intro' | 'outro'
  label?: string
  chapter?: string
  card?: Card
  narration?: { beats: Beat[]; [key: string]: unknown }
  transition_in?: { style?: string; duration?: number }
  [key: string]: unknown
}

export interface VideoSpec {
  spec_version?: string
  id?: string
  title: string
  source?: { kind: 'note' | 'brief'; [key: string]: unknown }
  segments: Segment[]
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
