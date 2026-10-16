import type { Anchor, Segment } from '@/api/projects'

/** Anchors as select values, for `AnchorSelect`. */

export interface AnchorOption {
  value: string
  label: string
}

/**
 * An anchor as one select value: `video_start`, `start:s_market`, `end:s_market:b2`
 * (a beat), or `start:` (the start of the scene the element belongs to, which the
 * spec writes by leaving `segment` out).
 */
export function anchorValue(anchor: Anchor | undefined): string {
  if (anchor === undefined) return ''
  if (typeof anchor === 'string') return anchor
  const base = `${anchor.edge}:${anchor.segment ?? ''}`
  return anchor.beat ? `${base}:${anchor.beat}` : base
}

export function anchorFrom(value: string, offset?: number): Anchor | undefined {
  if (value === '') return undefined
  if (value === 'video_start' || value === 'video_end') return value
  const [edge, segment, beat] = value.split(':')
  return {
    ...(segment ? { segment } : {}),
    ...(beat ? { beat } : {}),
    edge: edge as 'start' | 'end',
    ...(offset ? { offset } : {}),
  }
}

export const sceneName = (segment: Segment, index: number) =>
  segment.label || `Scene ${index + 1}`

/** The start and end of every scene, and of the video. */
export function sceneOptions(segments: Segment[]): AnchorOption[] {
  return [
    { value: 'video_start', label: 'start of the video' },
    ...segments.map((s, i) => ({
      value: `start:${s.id}`,
      label: `start of ${sceneName(s, i)}`,
    })),
    ...segments.map((s, i) => ({
      value: `end:${s.id}`,
      label: `end of ${sceneName(s, i)}`,
    })),
    { value: 'video_end', label: 'end of the video' },
  ]
}

export function offsetOf(anchor: Anchor | undefined): number {
  return anchor && typeof anchor !== 'string' ? (anchor.offset ?? 0) : 0
}
