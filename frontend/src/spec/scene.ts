import type { Frame, Motion, VideoSpec } from '@/api/projects'
import { updateSegment } from '@/spec/edits'

/**
 * A scene's transition and Ken Burns move, set from the scene card.
 *
 * `undefined` means "the project's default", which removes the field rather than
 * writing the default in: the spec's rule is that a scene overrides only what it says.
 */

export const TRANSITIONS = [
  { value: 'none', label: 'Cut' },
  { value: 'fade', label: 'Fade through black' },
  { value: 'fadewhite', label: 'Fade through white' },
  { value: 'dissolve', label: 'Dissolve' },
  { value: 'slideleft', label: 'Slide left' },
  { value: 'slideright', label: 'Slide right' },
  { value: 'wipeleft', label: 'Wipe left' },
  { value: 'wiperight', label: 'Wipe right' },
  { value: 'circleopen', label: 'Circle open' },
  { value: 'smoothleft', label: 'Smooth left' },
] as const

export const MOTIONS = [
  { value: 'none', label: 'Still' },
  { value: 'zoom_in', label: 'Zoom in' },
  { value: 'zoom_out', label: 'Zoom out' },
  { value: 'pan_left', label: 'Pan left' },
  { value: 'pan_right', label: 'Pan right' },
  { value: 'pan_up', label: 'Pan up' },
  { value: 'pan_down', label: 'Pan down' },
  { value: 'path', label: 'Move between two frames' },
] as const

/**
 * The moves a project can default to. No path, which is one picture's framing and the
 * spec refuses project-wide; `alternate` instead, which only makes sense project-wide:
 * it cycles zoom and pan scene by scene, so a run of stills doesn't all move alike.
 */
export const PROJECT_MOTIONS = [
  ...MOTIONS.filter((m) => m.value !== 'path'),
  { value: 'alternate', label: 'Alternate zooms and pans' },
] as const

/** A move in words; unset is the spec's own default, which is no move. */
export function motionLabel(effect: string | undefined): string {
  return (
    PROJECT_MOTIONS.find((m) => m.value === (effect ?? 'none'))?.label ?? effect ?? ''
  )
}

/** The spec's default `amount` for a preset move (`Motion.amount` in model.py). */
export const DEFAULT_MOTION_AMOUNT = 0.12

/**
 * The project's default move, which every still without one of its own follows.
 * A still default at the default amount removes `style.motion` rather than writing
 * the spec's default back in.
 */
export function setProjectMotion(
  spec: VideoSpec,
  motion: { effect: string; amount?: number }
): VideoSpec {
  const style = { ...(spec.style ?? {}) }
  if (motion.effect === 'none' && motion.amount === undefined) delete style.motion
  else style.motion = motion
  return { ...spec, style }
}

export function setTransition(
  spec: VideoSpec,
  index: number,
  transition: { style?: string; duration?: number } | undefined
): VideoSpec {
  return updateSegment(spec, index, (segment) => {
    const next = { ...segment }
    if (transition === undefined) delete next.transition_in
    else next.transition_in = transition
    return next
  })
}

/** The whole picture to its middle third: a sensible first path to adjust. */
export const DEFAULT_PATH: { from: Frame; to: Frame } = {
  from: { x: 0, y: 0, w: 1 },
  to: { x: 0.3, y: 0.3, w: 0.4 },
}

export function setMotion(
  spec: VideoSpec,
  index: number,
  motion: Motion | undefined
): VideoSpec {
  return updateSegment(spec, index, (segment) => {
    if (!segment.visual) return segment
    const visual = { ...segment.visual }
    if (motion === undefined) delete visual.motion
    else visual.motion = motion
    return { ...segment, visual }
  })
}

/**
 * Keep a frame inside the picture: its width within (0, 1], its left and top edges
 * such that the frame (whose height comes from the output's shape) still fits.
 */
export function clampFrame(frame: Frame, frameHeightPerWidth: number): Frame {
  const w = Math.min(1, Math.max(0.05, frame.w))
  const h = Math.min(1, w * frameHeightPerWidth)
  const round = (n: number) => Math.round(n * 1000) / 1000
  return {
    w: round(w),
    x: round(Math.min(Math.max(0, frame.x), 1 - w)),
    y: round(Math.min(Math.max(0, frame.y), Math.max(0, 1 - h))),
  }
}
