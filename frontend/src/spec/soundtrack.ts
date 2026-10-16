import type { GamAsset } from '@/api/gam'
import type { Anchor, AudioTrack, VideoSpec } from '@/api/projects'
import { assetKeyFor } from '@/spec/footage'

/**
 * Audio tracks: music, sound effects, extra voice, each placed against the scenes.
 *
 * A soundtrack that changes through the video is several tracks, and a crossfade is
 * two that overlap with matching fades. Tracks anchor to scenes, never to seconds, so
 * inserting or rewording a scene never leaves a track ending in the wrong place.
 */

function nextTrackId(spec: VideoSpec, prefix: string): string {
  const taken = new Set((spec.audio_tracks ?? []).map((t) => t.id))
  let n = (spec.audio_tracks ?? []).length + 1
  while (taken.has(`${prefix}_${n}`)) n += 1
  return `${prefix}_${n}`
}

export function addTrack(
  spec: VideoSpec,
  asset: GamAsset,
  kind: 'music' | 'sfx' | 'voiceover',
  from: string,
  to?: string
): VideoSpec {
  const key = assetKeyFor(spec, asset)
  const assets = spec.assets?.[key]
    ? spec.assets
    : {
        ...(spec.assets ?? {}),
        [key]: {
          from: 'gam' as const,
          id: asset.id,
          type: asset.asset_type,
          label: asset.name,
        },
      }
  const track: AudioTrack = {
    id: nextTrackId(spec, kind === 'music' ? 'm' : kind === 'sfx' ? 'x' : 'v'),
    kind,
    asset: key,
    start: { segment: from, edge: 'start' },
    ...(to ? { end: { segment: to, edge: 'end' } as Anchor } : {}),
    volume: kind === 'music' ? 0.18 : 0.6,
    fade_in: kind === 'music' ? 1.5 : 0,
    fade_out: kind === 'music' ? 3 : 0,
  }
  return { ...spec, assets, audio_tracks: [...(spec.audio_tracks ?? []), track] }
}

export function updateTrack(
  spec: VideoSpec,
  index: number,
  patch: Partial<AudioTrack>
): VideoSpec {
  return {
    ...spec,
    audio_tracks: (spec.audio_tracks ?? []).map((t, i) => {
      if (i !== index) return t
      const next = { ...t, ...patch }
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined) delete next[k as keyof AudioTrack]
      }
      return next
    }),
  }
}

export function removeTrack(spec: VideoSpec, index: number): VideoSpec {
  return {
    ...spec,
    audio_tracks: (spec.audio_tracks ?? []).filter((_, i) => i !== index),
  }
}

/**
 * Crossfade from the track before this one into this one, over `seconds`.
 *
 * This track starts `seconds` before its scene does and fades in over them; the one
 * before ends exactly where this one's scene starts and fades out over the same
 * span, so the two overlap by exactly the crossfade, wherever that scene moves to.
 */
export function crossfadeInto(
  spec: VideoSpec,
  index: number,
  seconds: number
): VideoSpec {
  const tracks = spec.audio_tracks ?? []
  const track = tracks[index]
  const previous = tracks[index - 1]
  if (!track || !previous || typeof track.start === 'string') return spec
  const scene = track.start.segment
  let next = updateTrack(spec, index, {
    start: { segment: scene, edge: 'start', offset: -seconds },
    fade_in: seconds,
  })
  next = updateTrack(next, index - 1, {
    end: { segment: scene, edge: 'start' },
    fade_out: seconds,
  })
  return next
}

/** "Scene 3 start" for an anchor, given the scenes' labels. */
export function describeAnchor(
  anchor: Anchor | undefined,
  labels: Record<string, string>
): string {
  if (anchor === undefined) return 'its own end'
  if (anchor === 'video_start') return 'the start of the video'
  if (anchor === 'video_end') return 'the end of the video'
  const name = anchor.segment ? (labels[anchor.segment] ?? anchor.segment) : 'this scene'
  const offset = anchor.offset
    ? ` ${anchor.offset > 0 ? '+' : '−'}${Math.abs(anchor.offset)} s`
    : ''
  return `${anchor.edge === 'start' ? 'start' : 'end'} of ${name}${offset}`
}
