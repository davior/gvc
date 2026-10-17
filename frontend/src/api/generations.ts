import client from '@/api/client'
import type { VideoSpec } from '@/api/projects'

/**
 * Pictures and clips generated for a project's placeholders. GAM runs each one on
 * fal.ai with the user's own key; GVC keeps a row per generation and catches it up
 * from GAM whenever the list is read, so one started and left still lands.
 */

export type GenerationStatus = 'queued' | 'processing' | 'done' | 'error' | 'cancelled'

export interface Generation {
  id: string
  project_id: string | null
  /** The placeholder it is for. */
  asset_key: string
  kind: 'text_to_image' | 'image_to_image' | 'image_to_video' | string
  prompt: string
  model_label: string
  status: GenerationStatus
  stage: string
  progress: number
  detail: string
  error: string | null
  /** GAM asset ids, in the order made. */
  result_ids: string[]
  /** The output put in the video, once one has been. */
  used_id: string | null
  /** List price × units, before it runs; what fal.ai charged is in GAM's usage. */
  estimate: number | null
  created_at: string
  updated_at: string
}

export interface GenerationModel {
  id: string
  kind: string
  label: string
  note: string
  /** "$0.07 a second" */
  price: string
  unit_price: number | null
  price_unit: 'image' | 'megapixel' | 'second' | 'video' | string | null
  /** The model's own choices, spelled and typed as GAM wants them back. */
  options: {
    aspect_ratios?: string[]
    image_sizes?: string[]
    durations?: (string | number)[]
    max_outputs?: number
    [key: string]: unknown
  }
}

export interface GenerationStart {
  asset_key: string
  prompt?: string
  model_id?: string
  outputs?: number
  duration?: string
  base_gam_ids?: string[]
  /** The editor's unsaved draft, so a placeholder added since the last save counts. */
  draft_spec?: VideoSpec
}

export const RUNNING: GenerationStatus[] = ['queued', 'processing']

interface DataResponse<T> {
  data: T
}

export const generationsApi = {
  models(): Promise<GenerationModel[]> {
    return client
      .get<DataResponse<GenerationModel[]>>('/gam/generation-models')
      .then((r) => r.data.data)
  },

  list(projectId: string): Promise<Generation[]> {
    return client
      .get<DataResponse<Generation[]>>(`/projects/${projectId}/generations`)
      .then((r) => r.data.data)
  },

  start(projectId: string, body: GenerationStart): Promise<Generation> {
    return client
      .post<DataResponse<Generation>>(`/projects/${projectId}/generations`, body)
      .then((r) => r.data.data)
  },

  use(id: string, assetId: string): Promise<Generation> {
    return client
      .post<DataResponse<Generation>>(`/generations/${id}/use`, { asset_id: assetId })
      .then((r) => r.data.data)
  },

  cancel(id: string): Promise<Generation> {
    return client
      .delete<DataResponse<Generation>>(`/generations/${id}`)
      .then((r) => r.data.data)
  },
}
