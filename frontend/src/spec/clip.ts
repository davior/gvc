import type { GamAsset } from '@/api/gam'
import type { Segment, Trim, VideoSpec } from '@/api/projects'
import { updateSegment } from '@/spec/edits'

/**
 * A scene's footage, timed by hand: its in and out points, how long the scene runs,
 * and whether short footage loops or holds. Pure functions from one spec to the next,
 * as in `edits.ts`.
 */

/** The shortest stretch a trim may leave; anything less is not a shot. */
export const MIN_TRIM_SECONDS = 0.1

// The render's reading-rate guess (`render/estimate.py`) and the spec's defaults. The
// real length is only known once the narration has been spoken, so the editor says
// "about".
const CHARS_PER_SECOND = 15
const PARAGRAPH_PAUSE_MS = 350
const SEGMENT_END_PAUSE_MS = 600
const MIN_SEGMENT_SECONDS = 2.5

// Joins that overlap two shots; a cut and a dip through a colour do not.
const NOT_BLENDS = ['none', 'fade', 'fadewhite']

const tenth = (n: number) => Math.round(n * 10) / 10

/** A GAM clip is a stretch of its parent's file, which is what `file_url` serves. */
function isClip(asset: GamAsset): boolean {
  return !!asset.parent_asset_id && asset.in_point !== null
}

/** The GAM asset a scene's visual is, once its ref names one; null while it doesn't. */
export function footageOf(
  spec: VideoSpec,
  segment: Segment,
  gamAssets: Record<string, GamAsset | null>
): GamAsset | null {
  const ref = segment.visual ? spec.assets?.[segment.visual.asset] : undefined
  const id =
    ref?.from === 'gam'
      ? ref.id
      : ref?.from === 'search' || ref?.from === 'generate'
        ? ref.result?.id
        : undefined
  const asset = id ? gamAssets[id] : null
  return asset && !asset.missing && asset.file_url ? asset : null
}

/** How long the asset is, in seconds, when GAM says. */
export function assetLength(asset: GamAsset): number | null {
  if (isClip(asset) && asset.out_point !== null)
    return asset.out_point - (asset.in_point ?? 0)
  return asset.duration_seconds
}

/** How long the trimmed footage plays for, when that is known. */
export function footageSeconds(asset: GamAsset, trim?: Trim): number | null {
  if (trim?.out !== undefined) return trim.out - trim.in
  const length = assetLength(asset)
  return length === null ? null : Math.max(0, length - (trim?.in ?? 0))
}

/** Where the trimmed footage sits in the file the player loads. */
export function playWindow(
  asset: GamAsset,
  trim?: Trim
): { start: number; end: number | null } {
  const offset = isClip(asset) ? (asset.in_point ?? 0) : 0
  const length = assetLength(asset)
  const end = trim?.out !== undefined ? trim.out : length !== null ? length : null
  return { start: offset + (trim?.in ?? 0), end: end === null ? null : offset + end }
}

/**
 * A trim held inside the asset and at least `MIN_TRIM_SECONDS` long. `edge` is the end
 * that moved: when the two would cross, the other end gives way only if it has to.
 */
export function clampTrim(
  trim: Trim,
  length: number | null,
  edge: 'in' | 'out' = 'in'
): Trim {
  const top = length ?? Infinity
  let a = Math.max(0, tenth(trim.in))
  let b = trim.out === undefined ? undefined : Math.min(top, tenth(trim.out))
  if (b !== undefined && b - a < MIN_TRIM_SECONDS) {
    if (edge === 'in') a = Math.max(0, tenth(b - MIN_TRIM_SECONDS))
    else b = Math.min(top, tenth(a + MIN_TRIM_SECONDS))
    if (b - a < MIN_TRIM_SECONDS) a = Math.max(0, tenth(b - MIN_TRIM_SECONDS))
  }
  if (a >= top) a = Math.max(0, tenth(top - MIN_TRIM_SECONDS))
  return b === undefined ? { in: a } : { in: a, out: b }
}

/** Move one end of a trim to `seconds` into the asset. */
export function trimAt(
  trim: Trim | undefined,
  edge: 'in' | 'out',
  seconds: number,
  length: number | null
): Trim {
  const base: Trim = trim ?? { in: 0, ...(length !== null ? { out: length } : {}) }
  const moved = edge === 'in' ? { ...base, in: seconds } : { ...base, out: seconds }
  return clampTrim(moved, length, edge)
}

/** Move one end of a trim by `delta` seconds. An open end starts from the asset's end. */
export function nudge(
  trim: Trim | undefined,
  edge: 'in' | 'out',
  delta: number,
  length: number | null
): Trim {
  const from = edge === 'in' ? (trim?.in ?? 0) : (trim?.out ?? length ?? trim?.in ?? 0)
  return trimAt(trim, edge, from + delta, length)
}

/** Set a scene's trim; undefined plays the footage whole. */
export function setTrim(
  spec: VideoSpec,
  index: number,
  trim: Trim | undefined
): VideoSpec {
  return updateSegment(spec, index, (segment) => {
    if (!segment.visual) return segment
    const visual = { ...segment.visual, trim }
    if (!trim) delete visual.trim
    return { ...segment, visual }
  })
}

/** Fix a scene's length in seconds; undefined lets it follow its narration again. */
export function setLength(spec: VideoSpec, index: number, fixed: number | undefined) {
  return updateSegment(spec, index, (segment) => {
    const duration = {
      ...segment.duration,
      fixed: fixed === undefined ? fixed : tenth(fixed),
    }
    if (fixed === undefined) delete duration.fixed
    const next: Segment = { ...segment, duration }
    if (Object.keys(duration).length === 0) delete next.duration
    return next
  })
}

/** Whether footage shorter than its scene repeats (true) or holds its last frame. */
export function setLoop(spec: VideoSpec, index: number, loop: boolean): VideoSpec {
  return updateSegment(spec, index, (segment) =>
    segment.visual ? { ...segment, visual: { ...segment.visual, loop } } : segment
  )
}

/** Roughly how long a scene runs: its fixed length, else its narration or the floor. */
export function sceneSeconds(spec: VideoSpec, segment: Segment): number {
  if (segment.duration?.fixed) return segment.duration.fixed
  const beats = (segment.narration?.beats ?? []).filter((b) => b.speak !== false)
  const chars = beats.reduce((n, b) => n + b.text.length, 0)
  const voice = spec.voice as { speed?: number } | undefined
  const own = segment.narration?.voice as { speed?: number } | undefined
  const speed = Math.max(0.5, own?.speed ?? voice?.speed ?? 1)
  const pauses = (segment.narration?.beats ?? []).reduce(
    (ms, b, i, all) =>
      ms +
      ((b.pause_after_ms as number | undefined) ??
        (i === all.length - 1 ? SEGMENT_END_PAUSE_MS : PARAGRAPH_PAUSE_MS)),
    0
  )
  const spoken = chars ? chars / CHARS_PER_SECOND / speed + pauses / 1000 : 0
  const style = spec.style as { min_segment_seconds?: number } | undefined
  const floor = segment.duration?.min ?? style?.min_segment_seconds ?? MIN_SEGMENT_SECONDS
  return Math.max(floor, spoken)
}

function blendInto(
  spec: VideoSpec,
  index: number
): { style: string; seconds: number } | null {
  const next = spec.segments[index + 1]
  if (!next) return null
  const style = next.transition_in?.style ?? spec.style?.transition?.style ?? 'none'
  if (NOT_BLENDS.includes(style)) return null
  return {
    style,
    seconds: next.transition_in?.duration ?? spec.style?.transition?.duration ?? 0.6,
  }
}

/**
 * Why the footage and its scene won't line up, in one sentence, or null when they do.
 *
 * A muted scene runs for its narration, so footage of another length loops, holds or
 * is cut short without saying so: this says so. A clip runs for its footage, and a
 * blend out of it plays a moment past the out point rather than cutting its last
 * words (`compile.layout`).
 */
export function timingNote(
  spec: VideoSpec,
  index: number,
  asset: GamAsset
): string | null {
  const segment = spec.segments[index]
  if (!segment?.visual || asset.asset_type !== 'video') return null
  const footage = footageSeconds(asset, segment.visual.trim)
  if (segment.kind === 'clip') {
    const blend = blendInto(spec, index)
    return blend
      ? `The ${blend.style} into the next scene plays up to ${blend.seconds} s past the out point.`
      : null
  }
  if (segment.kind !== 'scene' || footage === null) return null
  const scene = sceneSeconds(spec, segment)
  const about = segment.duration?.fixed ? '' : 'about '
  const gap = tenth(scene - footage)
  const said = `Footage is ${tenth(footage)} s; the scene runs ${about}${tenth(scene)} s`
  if (gap > 0.3)
    return segment.visual.loop === false
      ? `${said}, so it holds its last frame for ${gap} s.`
      : `${said}, so it loops.`
  if (gap < -0.3) return `${said}, so its last ${-gap} s aren’t shown.`
  return null
}
