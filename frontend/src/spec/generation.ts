import type { Generation, GenerationModel } from '@/api/generations'
import type { AssetRef, VideoSpec } from '@/api/projects'

/** Generate placeholders, and putting what was generated into a spec. Pure. */

export type GenerateRef = Extract<AssetRef, { from: 'generate' }>

/** Only pictures and clips: GAM has no models for music or sound. */
export function canGenerate(ref: GenerateRef): boolean {
  return ref.type === 'image' || ref.type === 'video'
}

/** The generate placeholders with nothing in them yet, with their keys. */
export function unmadeGenerates(spec: VideoSpec): { key: string; ref: GenerateRef }[] {
  return Object.entries(spec.assets ?? {}).flatMap(([key, ref]) =>
    ref.from === 'generate' && !ref.result ? [{ key, ref }] : []
  )
}

/**
 * Fill a placeholder with one output. The key stays a generate ref, so the prompt that
 * made the picture is still there to make another.
 */
export function fillGenerated(spec: VideoSpec, key: string, assetId: string): VideoSpec {
  const ref = spec.assets?.[key]
  if (!ref || ref.from !== 'generate') return spec
  return {
    ...spec,
    assets: {
      ...spec.assets,
      [key]: { ...ref, status: 'ready', result: { from: 'gam', id: assetId } },
    },
  }
}

/** The latest generation for each placeholder. The list comes oldest first. */
export function latestByKey(rows: Generation[]): Record<string, Generation> {
  const latest: Record<string, Generation> = {}
  for (const row of rows) latest[row.asset_key] = row
  return latest
}

/** The kind of model a placeholder needs. */
export function kindFor(ref: GenerateRef, hasBase: boolean): string {
  if (ref.type === 'video') return 'image_to_video'
  return hasBase ? 'image_to_image' : 'text_to_image'
}

const number = (v: string | number) => parseFloat(String(v))

/**
 * What a run should cost at list price, or null when that depends on something the
 * editor doesn't know (a per-megapixel price at a size GAM picks).
 */
export function estimateCost(
  model: GenerationModel,
  outputs: number,
  duration?: string | number
): number | null {
  const price = model.unit_price
  if (price === null || price === undefined) return null
  switch (model.price_unit) {
    case 'image':
    case 'video':
      return price * outputs
    case 'second': {
      const seconds = duration ?? model.options.durations?.[0]
      return seconds === undefined ? null : price * number(seconds) * outputs
    }
    default:
      return null
  }
}

/** `0.284` → `$0.28`; small sums keep a third place so they don't read as nothing. */
export function dollars(n: number): string {
  return n < 0.1 ? `$${n.toFixed(3)}` : `$${n.toFixed(2)}`
}
