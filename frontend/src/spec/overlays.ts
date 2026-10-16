import type { GamAsset } from '@/api/gam'
import type { Credits, Overlay, Segment, VideoSpec } from '@/api/projects'
import { withGamAsset } from '@/spec/footage'

/**
 * On-screen text, lower thirds and pictures over a scene, and the end credits, as
 * pure functions from one spec to the next (the rules of `edits.ts`).
 *
 * Quote and code overlays are left alone here: they are their own shots, and the
 * scene editor already treats them as beats.
 */

export const TIMED_TYPES = ['text', 'lower_third', 'image'] as const
export type TimedType = (typeof TIMED_TYPES)[number]

export function isTimed(overlay: Overlay): boolean {
  return (TIMED_TYPES as readonly string[]).includes(overlay.type)
}

/** Unique across the whole spec, though the spec only requires it per segment, so an
 *  overlay keeps its id if the editor later moves it between scenes. */
export function newOverlayId(spec: VideoSpec): string {
  const taken = new Set(spec.segments.flatMap((s) => (s.overlays ?? []).map((o) => o.id)))
  let n = taken.size + 1
  while (taken.has(`o_${n}`)) n += 1
  return `o_${n}`
}

function withSegment(
  spec: VideoSpec,
  index: number,
  change: (segment: Segment) => Segment
): VideoSpec {
  return { ...spec, segments: spec.segments.map((s, i) => (i === index ? change(s) : s)) }
}

export function addOverlay(
  spec: VideoSpec,
  index: number,
  type: 'text' | 'lower_third'
): VideoSpec {
  const id = newOverlayId(spec)
  const overlay: Overlay =
    type === 'text'
      ? { id, type: 'text', text: 'Text on screen', position: 'center' }
      : { id, type: 'lower_third', title: 'Name', subtitle: 'Role' }
  return withSegment(spec, index, (s) => ({
    ...s,
    overlays: [...(s.overlays ?? []), overlay],
  }))
}

export function addImageOverlay(
  spec: VideoSpec,
  index: number,
  asset: GamAsset
): VideoSpec {
  const [withAsset, key] = withGamAsset(spec, asset)
  const overlay: Overlay = {
    id: newOverlayId(spec),
    type: 'image',
    asset: key,
    position: 'top-right',
    scale_pct: 25,
  }
  return withSegment(withAsset, index, (s) => ({
    ...s,
    overlays: [...(s.overlays ?? []), overlay],
  }))
}

export function updateOverlay(
  spec: VideoSpec,
  index: number,
  id: string,
  patch: Partial<Overlay>
): VideoSpec {
  return withSegment(spec, index, (s) => ({
    ...s,
    overlays: (s.overlays ?? []).map((o) => {
      if (o.id !== id) return o
      const next = { ...o, ...patch } as Record<string, unknown>
      // A field set back to "default" is removed, not stored as undefined.
      for (const [k, v] of Object.entries(next)) if (v === undefined) delete next[k]
      return next as Overlay
    }),
  }))
}

export function removeOverlay(spec: VideoSpec, index: number, id: string): VideoSpec {
  return withSegment(spec, index, (s) => ({
    ...s,
    overlays: (s.overlays ?? []).filter((o) => o.id !== id),
  }))
}

/** The credits on (with the given settings) or off (`null`). */
export function setCredits(spec: VideoSpec, credits: Credits | null): VideoSpec {
  const next = { ...spec }
  if (credits === null) delete next.credits
  else next.credits = credits
  return next
}
