import client from '@/api/client'

/** Rendering a project, following the render, and its finished files. */

export type RenderStatus = 'queued' | 'processing' | 'done' | 'error' | 'cancelled'

export interface Render {
  id: string
  project_id: string
  /** The project version rendered; later edits never change it. */
  version: number
  preview: boolean
  status: RenderStatus
  stage: string
  progress: number
  detail: string
  error: string | null
  warnings: string[]
  duration: number | null
  size_bytes: number | null
  narration_chars: number
  /** Signed and short-lived: refetch the render for fresh ones. */
  video_url: string | null
  subtitles_url: string | null
  poster_url: string | null
  created_at: string
  updated_at: string
}

export interface Estimate {
  seconds: number
  /** True when a clip's length is unknown, so `seconds` is a lower bound. */
  seconds_is_floor: boolean
  narration_chars: number
  /** Reasons a full render would be refused, and a preview. */
  blocks_render: string[]
  blocks_preview: string[]
}

export const ACTIVE: RenderStatus[] = ['queued', 'processing']

interface DataResponse<T> {
  data: T
}

interface ListResponse<T> {
  data: T[]
  total: number
}

export const rendersApi = {
  estimate(projectId: string): Promise<Estimate> {
    return client
      .post<DataResponse<Estimate>>(`/projects/${projectId}/estimate`)
      .then((r) => r.data.data)
  },

  start(projectId: string, preview: boolean): Promise<Render> {
    return client
      .post<DataResponse<Render>>(`/projects/${projectId}/renders`, { preview })
      .then((r) => r.data.data)
  },

  list(projectId: string): Promise<Render[]> {
    return client
      .get<ListResponse<Render>>(`/projects/${projectId}/renders`)
      .then((r) => r.data.data)
  },

  get(id: string): Promise<Render> {
    return client.get<DataResponse<Render>>(`/renders/${id}`).then((r) => r.data.data)
  },

  cancel(id: string): Promise<Render> {
    return client
      .post<DataResponse<Render>>(`/renders/${id}/cancel`)
      .then((r) => r.data.data)
  },

  remove(id: string): Promise<void> {
    return client.delete(`/renders/${id}`).then(() => undefined)
  },
}
