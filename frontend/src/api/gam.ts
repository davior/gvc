import client from '@/api/client'
import type { WebImage } from '@/api/web'

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
  /** GAM's own page for the asset, to open it in the library. */
  page_url?: string | null
  parent_asset_id: string | null
  in_point: number | null
  out_point: number | null
  missing: boolean
  /** What a track sounds like (GAM's music profile). Null when GAM knows nothing about
   *  it, or is older than the profile. Optional for test literals that predate it. */
  music?: GamMusic | null
  /** What GAM says the audio is. Null when not known, or from a GAM before gam#49. */
  audio_kind?: 'music' | 'speech' | 'sfx' | null
}

export interface GamMusic {
  genres: string[]
  moods: string[]
  instruments: string[]
  bpm: number | null
  key: string | null
  /** Null is "not known", which is not false ("instrumental"). */
  vocals: boolean | null
  energy: 'low' | 'medium' | 'high' | string | null
}

/**
 * One line saying what a track sounds like: "Ambient, Tense · 92 BPM · Am · Low energy ·
 * Instrumental". Empty when nothing is known, so the caller can leave the line out.
 */
export function musicSummary(music: GamMusic | null | undefined): string {
  if (!music) return ''
  const parts: string[] = []
  const words = [...music.genres, ...music.moods, ...music.instruments]
  if (words.length) parts.push(words.join(', '))
  if (music.bpm !== null) parts.push(`${Math.round(music.bpm)} BPM`)
  if (music.key) parts.push(music.key)
  if (music.energy)
    parts.push(`${music.energy[0].toUpperCase()}${music.energy.slice(1)} energy`)
  if (music.vocals !== null) parts.push(music.vocals ? 'Vocals' : 'Instrumental')
  return parts.join(' · ')
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
  /** The moment is a cut already chosen (a playlist item's range), to use as it is. */
  exact?: boolean
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

/**
 * What an audio player draws its scrub bar from: peak amplitudes in 0..1, evenly over
 * `duration` seconds. GAM computes it once per file and caches it (gam#54), so the
 * browser never has to download a whole track to draw one.
 */
export interface GamWaveform {
  duration: number
  peaks: number[]
}

interface DataResponse<T> {
  data: T
}

/** A playlist in GAM (gam#70): named, ordered moments, which a video can start from. */
export interface GamPlaylist {
  id: string
  name: string
  description: string | null
  item_count: number
  total_seconds: number
  thumb_url: string | null
  updated_at: string | null
}

/** One entry of a GAM playlist: an asset and the stretch of it to play. `start`/`end`
 *  are resolved by GAM (the whole file when the item has no range); `in_point` and
 *  `out_point` are what is stored, both null for a whole asset. */
export interface GamPlaylistItem {
  id: string
  asset_id: string
  asset_name: string
  asset_type: string
  in_point: number | null
  out_point: number | null
  start: number
  end: number | null
  image_seconds: number | null
  label: string | null
  note: string | null
  asset_duration_seconds: number | null
  width: number | null
  height: number | null
  file_url: string | null
  thumb_url: string | null
  missing: boolean
}

export interface GamPlaylistDetail extends GamPlaylist {
  items: GamPlaylistItem[]
}

/** An item to put in a playlist, as GAM takes it. GAM checks it is yours and playable. */
export interface PlaylistItemIn {
  asset_id: string
  in_point?: number
  out_point?: number
  image_seconds?: number
  label?: string
  note?: string
}

/**
 * A playlist item as a search hit, so it is previewed and placed the way a hit is. Its
 * range is `exact`: the cut someone chose, used as it is.
 */
export function playlistItemHit(item: GamPlaylistItem): GamHit {
  const ranged = item.asset_type !== 'image' && item.in_point !== null
  return {
    asset: {
      id: item.asset_id,
      name: item.asset_name,
      asset_type: item.asset_type,
      duration_seconds: item.asset_duration_seconds,
      width: item.width,
      height: item.height,
      file_url: item.file_url,
      thumb_url: item.thumb_url,
      credit: '',
      parent_asset_id: null,
      in_point: null,
      out_point: null,
      missing: item.missing,
    },
    score: 0,
    snippet: item.label ?? '',
    start_time: ranged ? item.start : null,
    end_time: ranged ? item.end : null,
    exact: ranged,
  }
}

/** What a hit would be as a playlist item: its moment, else the whole asset. */
export function playlistItemFor(
  hit: GamHit,
  trim?: { in: number; out: number }
): PlaylistItemIn {
  const item: PlaylistItemIn = { asset_id: hit.asset.id }
  if (hit.asset.asset_type !== 'image' && trim) {
    item.in_point = trim.in
    item.out_point = trim.out
  }
  return item
}

interface ListResponse<T> {
  data: T[]
  total: number
}

export const gamApi = {
  /** Rejects with `gam_without_playlists` when GAM predates playlists. `q` keeps those
   *  whose name or description holds it. */
  playlists(q = ''): Promise<GamPlaylist[]> {
    return client
      .get<ListResponse<GamPlaylist>>('/gam/playlists', {
        params: q.trim() ? { q: q.trim() } : undefined,
      })
      .then((r) => r.data.data)
  },

  /** One playlist and its items in order. */
  playlist(id: string): Promise<GamPlaylistDetail> {
    return client
      .get<DataResponse<GamPlaylistDetail>>(`/gam/playlists/${id}`)
      .then((r) => r.data.data)
  },

  createPlaylist(body: {
    name: string
    description?: string
    items?: PlaylistItemIn[]
  }): Promise<GamPlaylistDetail> {
    return client
      .post<DataResponse<GamPlaylistDetail>>('/gam/playlists', body)
      .then((r) => r.data.data)
  },

  /** Adds at `position`, else at the end; all or none. Returns the playlist as it is now. */
  addPlaylistItems(
    id: string,
    items: PlaylistItemIn[],
    position?: number
  ): Promise<GamPlaylistDetail> {
    return client
      .post<DataResponse<GamPlaylistDetail>>(`/gam/playlists/${id}/items`, {
        items,
        position,
      })
      .then((r) => r.data.data)
  },

  /** Takes one item out; the asset stays in the library. */
  removePlaylistItem(id: string, itemId: string): Promise<GamPlaylistDetail> {
    return client
      .delete<DataResponse<GamPlaylistDetail>>(`/gam/playlists/${id}/items/${itemId}`)
      .then((r) => r.data.data)
  },

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

  /** Files a picture found on the web in the library, and returns the asset (an
   *  existing one when GAM already has it). GAM does the fetching. */
  importImage(image: WebImage): Promise<GamAsset> {
    return client
      .post<DataResponse<GamAsset>>('/gam/import-image', {
        image_url: image.image_url,
        page_url: image.page_url ?? null,
        title: image.title ?? '',
        description: image.description ?? '',
      })
      .then((r) => r.data.data)
  },

  /** Rejects when GAM has no waveform (422), so the player keeps its flat line. */
  peaks(id: string): Promise<GamWaveform> {
    return client
      .get<DataResponse<GamWaveform>>(`/gam/assets/${id}/peaks`)
      .then((r) => r.data.data)
  },
}

const KIND_LABELS = { music: 'Music', speech: 'Speech', sfx: 'Sound effect' } as const

/**
 * The line under an audio hit: what kind of audio it is, then what it sounds like.
 * "Speech" leads on purpose: a voice memo in a list of soundtracks should be the first
 * thing a person notices about it. A music track with a profile needs no "Music" label.
 */
export function audioSummary(asset: Pick<GamAsset, 'audio_kind' | 'music'>): string {
  const sound = musicSummary(asset.music)
  const kind = asset.audio_kind ? KIND_LABELS[asset.audio_kind] : ''
  if (asset.audio_kind === 'music' && sound) return sound
  return [kind, sound].filter(Boolean).join(' · ')
}
