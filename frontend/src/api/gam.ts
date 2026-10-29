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
