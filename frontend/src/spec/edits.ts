import type { Segment, VideoSpec } from '@/api/projects'

/**
 * The edits the scene list makes, as pure functions from one spec to the next.
 *
 * Pure so they are tested without rendering anything, and so the same functions can
 * back the storyboard (M3) and, later, the operations an AI proposes (M5). Each
 * returns a new spec and leaves every field it does not understand exactly as it was.
 */

/** The first id `prefix_n` not already taken. Ids are never reused within a spec. */
export function nextSegmentId(spec: VideoSpec, prefix = 's'): string {
  const taken = new Set(spec.segments.map((s) => s.id))
  let n = spec.segments.length
  while (taken.has(`${prefix}_${n}`)) n += 1
  return `${prefix}_${n}`
}

/** A new, empty scene after `afterIndex` (or at the end). */
export function addScene(spec: VideoSpec, afterIndex?: number): VideoSpec {
  const id = nextSegmentId(spec)
  const scenes = spec.segments.filter((s) => s.kind === 'scene').length
  const scene: Segment = {
    id,
    kind: 'scene',
    label: `Scene ${scenes + 1}`,
    narration: { beats: [{ id: 'b1', text: '' }] },
  }
  const at = afterIndex === undefined ? spec.segments.length : afterIndex + 1
  const segments = [...spec.segments]
  segments.splice(at, 0, scene)
  return { ...spec, segments }
}

/**
 * Move the segment at `index` by `delta` places, staying inside the list.
 *
 * Nothing that points at a segment needs fixing: audio tracks and overlays anchor to
 * ids, not positions, which is the whole reason the format uses ids.
 */
export function moveSegment(spec: VideoSpec, index: number, delta: number): VideoSpec {
  const target = index + delta
  if (target < 0 || target >= spec.segments.length || delta === 0) return spec
  const segments = [...spec.segments]
  const [moved] = segments.splice(index, 1)
  segments.splice(target, 0, moved)
  return { ...spec, segments }
}

/**
 * Remove a segment.
 *
 * Anchors that pointed at it are left as they are, and the spec stays valid: the
 * renderer drops what an orphaned anchor started (the Notes spec doc §5.7). Refusing
 * the delete instead would make "remove this scene" depend on finding and fixing
 * every track that mentions it first.
 */
export function removeSegment(spec: VideoSpec, index: number): VideoSpec {
  return { ...spec, segments: spec.segments.filter((_, i) => i !== index) }
}

export function updateSegment(
  spec: VideoSpec,
  index: number,
  change: (segment: Segment) => Segment
): VideoSpec {
  return {
    ...spec,
    segments: spec.segments.map((s, i) => (i === index ? change(s) : s)),
  }
}

/**
 * A scene's narration as one block of text, a paragraph per beat.
 *
 * The scene list edits narration as plain text; beats are how the format times it.
 * Paragraphs map onto beats one to one, and a beat keeps its id (and anything else
 * it carries, such as `kind` or `pause_after_ms`) as long as it keeps its position, so
 * an overlay anchored to beat `b2` still finds it after the words change.
 */
export function narrationText(segment: Segment): string {
  return (segment.narration?.beats ?? []).map((b) => b.text).join('\n\n')
}

export function withNarrationText(segment: Segment, text: string): Segment {
  const existing = segment.narration?.beats ?? []
  // Not trimmed: this runs on every keystroke and the box shows the result back, so
  // trimming would eat the space just typed at the end of a paragraph. Only a
  // paragraph of nothing but whitespace is normalised, to empty.
  const paragraphs = text.split(/\n\s*\n/).map((p) => (p.trim() === '' ? '' : p))
  // An emptied box is one empty beat, not none, so the scene keeps a place to type.
  const kept = paragraphs.filter((p, i) => p !== '' || i === 0)
  const taken = new Set(existing.map((b) => b.id))
  let n = existing.length
  const beats = kept.map((paragraph, i) => {
    if (i < existing.length) return { ...existing[i], text: paragraph }
    n += 1
    while (taken.has(`b${n}`)) n += 1
    taken.add(`b${n}`)
    return { id: `b${n}`, text: paragraph }
  })
  return { ...segment, narration: { ...(segment.narration ?? {}), beats } }
}
