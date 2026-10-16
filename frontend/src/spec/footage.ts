import type { GamAsset, GamHit } from '@/api/gam'
import type { AssetRef, Segment, Trim, VideoSpec } from '@/api/projects'

/**
 * Putting things found in GAM into a spec, as pure functions from one spec to the next.
 *
 * Same rules as `edits.ts`: each returns a new spec and leaves every field it does not
 * understand as it was. The spec only ever records GAM's asset id and the trim; the
 * signed URLs a hit carries expire and are fetched afresh to show anything.
 */

/** How long a moment is taken to be when GAM does not say where it ends (pre gam#36). */
export const DEFAULT_MOMENT_SECONDS = 5

export interface MomentSize {
  min?: number
  max?: number
  /** Seconds of lead-in and tail around what was said, so a cut does not clip a word. */
  pad?: number
}

const tenth = (n: number) => Math.round(n * 10) / 10

/**
 * The stretch of an asset to play for a hit: what was said, padded, then made at least
 * `min` and at most `max` long, and kept inside the asset.
 *
 * Undefined for a hit with no moment (a match on the file's name): the whole asset then.
 */
export function momentTrim(
  hit: GamHit,
  size: MomentSize = {}
): Required<Trim> | undefined {
  if (hit.start_time === null) return undefined
  const { min, max, pad = 0.5 } = size
  const start = hit.start_time
  const end = hit.end_time ?? start + DEFAULT_MOMENT_SECONDS
  let a = Math.max(0, start - pad)
  let b = end + pad

  if (min !== undefined && b - a < min) {
    // Widened around the middle of what was said, so the line stays in the cut.
    const centre = (start + end) / 2
    a = centre - min / 2
    b = centre + min / 2
    if (a < 0) {
      b -= a
      a = 0
    }
  }
  if (max !== undefined && b - a > max) b = a + max

  const duration = hit.asset.duration_seconds
  if (duration) {
    b = Math.min(b, duration)
    a = Math.max(0, Math.min(a, b - 0.1))
  }
  return { in: tenth(a), out: tenth(b) }
}

function slug(name: string): string {
  return name
    .toLowerCase()
    .replace(/\.[a-z0-9]{2,4}$/, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 24)
}

/**
 * The registry key for a GAM asset: the one already used for it, or a new readable one.
 * Reusing it means two scenes cut from the same interview share one entry, so swapping
 * the interview later is one edit.
 */
export function assetKeyFor(spec: VideoSpec, asset: GamAsset): string {
  const assets = spec.assets ?? {}
  for (const [key, ref] of Object.entries(assets)) {
    if (ref.from === 'gam' && ref.id === asset.id) return key
  }
  const base = `a_${slug(asset.name) || 'gam'}`
  let key = base
  for (let n = 2; key in assets; n += 1) key = `${base}_${n}`
  return key
}

export function withGamAsset(spec: VideoSpec, asset: GamAsset): [VideoSpec, string] {
  const key = assetKeyFor(spec, asset)
  if (spec.assets?.[key]) return [spec, key]
  const ref: AssetRef = {
    from: 'gam',
    id: asset.id,
    type: asset.asset_type,
    label: asset.name,
  }
  return [{ ...spec, assets: { ...(spec.assets ?? {}), [key]: ref } }, key]
}

/**
 * - `broll`: the scene's picture, muted and looped under its narration.
 * - `clip`: played with its own sound, nothing said over it. A clip carries no
 *   narration or overlays, so the segment's are dropped (Discard brings them back).
 */
export type PlaceMode = 'broll' | 'clip'

export function placeHit(
  spec: VideoSpec,
  index: number,
  hit: GamHit,
  mode: PlaceMode,
  size: MomentSize = {}
): VideoSpec {
  const [next, key] = withGamAsset(spec, hit.asset)
  const trim = hit.asset.asset_type === 'image' ? undefined : momentTrim(hit, size)
  const segments = next.segments.map((segment, i): Segment => {
    if (i !== index) return segment
    const fit = segment.visual?.fit
    const visual = {
      asset: key,
      ...(fit !== undefined ? { fit } : {}),
      ...(trim ? { trim } : {}),
      audio: mode === 'clip' ? ('play' as const) : ('mute' as const),
      loop: mode !== 'clip',
    }
    if (mode === 'clip') {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { narration: _n, overlays: _o, ...rest } = segment
      return { ...rest, kind: 'clip', visual }
    }
    return {
      ...segment,
      kind: 'scene',
      visual,
      narration: segment.narration ?? { beats: [{ id: 'b1', text: '' }] },
    }
  })
  return { ...next, segments }
}

/**
 * Back to the project's background: the picture goes, everything else stays.
 *
 * A clip is nothing but its footage, so a clip without one becomes an empty scene
 * rather than a spec that no longer validates.
 */
export function removeVisual(spec: VideoSpec, index: number): VideoSpec {
  return {
    ...spec,
    segments: spec.segments.map((segment, i): Segment => {
      if (i !== index) return segment
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { visual: _v, ...rest } = segment
      if (segment.kind !== 'clip') return rest
      return { ...rest, kind: 'scene', narration: { beats: [{ id: 'b1', text: '' }] } }
    }),
  }
}

/**
 * Resolve a `search` placeholder to what was found.
 *
 * The key stays a search ref (it records what was asked for, and why the asset is
 * there); `result` says what answered it. When the placeholder asked for a moment,
 * every segment showing it gets that moment as its trim.
 */
export function resolveSearch(spec: VideoSpec, key: string, hit: GamHit): VideoSpec {
  const ref = spec.assets?.[key]
  if (!ref || ref.from !== 'search') return spec
  const trim =
    ref.moment && hit.asset.asset_type !== 'image'
      ? momentTrim(hit, ref.moment)
      : undefined
  const resolved: AssetRef = {
    ...ref,
    type: ref.type ?? hit.asset.asset_type,
    status: 'resolved',
    result: { from: 'gam', id: hit.asset.id, ...(trim ?? {}) },
  }
  return {
    ...spec,
    assets: { ...spec.assets, [key]: resolved },
    segments: spec.segments.map((segment) =>
      trim && segment.visual?.asset === key
        ? { ...segment, visual: { ...segment.visual, trim } }
        : segment
    ),
  }
}

/** The `search` placeholders still waiting for footage, with their keys. */
export function unresolvedSearches(
  spec: VideoSpec
): { key: string; ref: Extract<AssetRef, { from: 'search' }> }[] {
  return Object.entries(spec.assets ?? {}).flatMap(([key, ref]) =>
    ref.from === 'search' && ref.status !== 'resolved' ? [{ key, ref }] : []
  )
}

/** The GAM ids a spec shows, including resolved placeholders: what to look up. */
export function gamIdsIn(spec: VideoSpec): string[] {
  const ids = Object.values(spec.assets ?? {}).flatMap((ref) =>
    ref.from === 'gam'
      ? [ref.id]
      : ref.from === 'search' && ref.result
        ? [ref.result.id]
        : []
  )
  return [...new Set(ids)]
}

/** `734.2` → `12:14`, `3725` → `1:02:05`. */
export function clock(seconds: number): string {
  const s = Math.floor(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
