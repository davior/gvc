import client from '@/api/client'

/**
 * GAM, the media library, searched and read through GVC's backend as the signed-in
 * user. The URLs here are absolute and signed by GAM, and they expire: use them to
 * show something now, never store them in a spec (a spec keeps only the asset id).
 */

export interface GamAsset {
  id: string
  name: string
  asset_type: 'image' | 'video' | 'audio' | string
  duration_seconds: number | null
  width: number | null
  height: number | null
  file_url: string | null
  thumb_url: string | null
  credit: string
  parent_asset_id: string | null
  in_point: number | null
  out_point: number | null
  missing: boolean
}

export interface GamHit {
  asset: GamAsset
  score: number
  /** Keyword hits wrap the matched words in «guillemets». */
  snippet: string
  /** The moment that matched, in seconds. Null for a hit on the file's name. */
  start_time: number | null
  /** Null on a GAM older than gam#36; the editor then sizes the moment itself. */
  end_time: number | null
}

export interface GamSearch {
  data: GamHit[]
  total: number
  query: string
  /** Whether GAM's meaning-based half ran; "no results" means less when it did not. */
  semantic: boolean
  semantic_error: string | null
}

export type MediaKind = 'image' | 'video' | 'audio'

interface DataResponse<T> {
  data: T
}

export const gamApi = {
  search(q: string, type?: MediaKind): Promise<GamSearch> {
    return client
      .get<GamSearch>('/gam/search', { params: { q, type, limit: 30 } })
      .then((r) => r.data)
  },

  /** Fresh names, thumbnails and URLs for the GAM assets a spec uses; null if gone. */
  lookup(ids: string[]): Promise<Record<string, GamAsset | null>> {
    if (ids.length === 0) return Promise.resolve({})
    return client
      .post<DataResponse<{ assets: Record<string, GamAsset | null> }>>(
        '/gam/assets/lookup',
        { ids }
      )
      .then((r) => r.data.data.assets)
  },
}
