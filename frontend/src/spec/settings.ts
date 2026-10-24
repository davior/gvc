import type { Output, VideoSpec, Voice, Waveform } from '@/api/projects'

type Pauses = NonNullable<Voice['pauses']>

/**
 * Project-wide settings as pure functions from one spec to the next (the rules of
 * `edits.ts`). Each setting is a field of the spec, so a project template can later be
 * nothing more than a partial spec applied over these same fields.
 */

/** The wave on (with these settings) or off (`null`). Off removes the block: "present
 *  means on" is the format's rule, and an emptied `chrome` is removed with it. */
export function setWaveform(spec: VideoSpec, waveform: Waveform | null): VideoSpec {
  const chrome = { ...(spec.chrome ?? {}) }
  if (waveform === null) delete chrome.waveform
  else chrome.waveform = waveform
  if (Object.keys(chrome).length > 0) return { ...spec, chrome }
  const rest = { ...spec }
  delete rest.chrome
  return rest
}

/**
 * What the spec means by a field that is left out. These are the model's own defaults
 * (backend `app/spec/model.py`); the controls show them, and a setting put back to its
 * default is removed rather than written out, so a spec keeps to what was actually said.
 */
export const OUTPUT_DEFAULTS = {
  aspect: '16:9',
  resolution: '1080p',
  quality: 'standard',
  fps: 30,
  subtitles: 'sidecar',
  chapters: true,
  thumbnail: true,
} as const

export const VOICE_DEFAULTS = {
  speed: 1,
  pauses: { paragraph_ms: 350, heading_ms: 800, segment_end_ms: 600 },
} as const

export function setOutput(spec: VideoSpec, patch: Partial<Output>): VideoSpec {
  const output: Record<string, unknown> = { ...(spec.output ?? {}), ...patch }
  for (const [key, value] of Object.entries(output)) {
    if (
      value === undefined ||
      value === (OUTPUT_DEFAULTS as Record<string, unknown>)[key]
    )
      delete output[key]
  }
  return withSection(spec, 'output', output)
}

export function setVoice(
  spec: VideoSpec,
  patch: { voice?: string; speed?: number; pauses?: Partial<Pauses> }
): VideoSpec {
  const voice: Record<string, unknown> = { ...(spec.voice ?? {}) }
  if ('voice' in patch) voice.voice = patch.voice?.trim() ? patch.voice.trim() : undefined
  if ('speed' in patch) voice.speed = patch.speed
  if (patch.pauses) {
    const pauses: Record<string, unknown> = {
      ...(spec.voice?.pauses ?? {}),
      ...patch.pauses,
    }
    for (const [key, value] of Object.entries(pauses)) {
      if (value === (VOICE_DEFAULTS.pauses as Record<string, unknown>)[key])
        delete pauses[key]
    }
    voice.pauses = Object.keys(pauses).length > 0 ? pauses : undefined
  }
  if (voice.speed === VOICE_DEFAULTS.speed) voice.speed = undefined
  for (const [key, value] of Object.entries(voice))
    if (value === undefined) delete voice[key]
  return withSection(spec, 'voice', voice)
}

/** A section with nothing left in it is removed, not kept as `{}`. */
function withSection(
  spec: VideoSpec,
  key: 'output' | 'voice',
  value: Record<string, unknown>
): VideoSpec {
  const next: Record<string, unknown> = { ...spec }
  if (Object.keys(value).length > 0) next[key] = value
  else delete next[key]
  return next as VideoSpec
}

type Obj = Record<string, unknown>

/** `fn` applied to the object at `path`, with an object left empty removed all the way
 *  up, so putting the last setting in a group back to its default removes the group. */
function updateAt(
  node: unknown,
  path: string[],
  fn: (current: Obj) => Obj
): Obj | undefined {
  const here = (node ?? {}) as Obj
  if (path.length === 0) {
    const next = fn(here)
    return Object.keys(next).length > 0 ? next : undefined
  }
  const [head, ...rest] = path
  const child = updateAt(here[head], rest, fn)
  const out: Obj = { ...here }
  if (child === undefined) delete out[head]
  else out[head] = child
  return Object.keys(out).length > 0 ? out : undefined
}

/**
 * Set fields of a group of settings (e.g. `['style', 'cards', 'title']`). A field put
 * back to its default, or set to `undefined`, is removed, so a spec keeps to what was
 * actually said and a template over these fields stays small.
 */
export function patchSetting(
  spec: VideoSpec,
  path: string[],
  patch: Obj,
  defaults: Obj
): VideoSpec {
  const next = updateAt(spec, path, (current) => {
    const merged: Obj = { ...current, ...patch }
    for (const [key, value] of Object.entries(merged)) {
      if (value === undefined || JSON.stringify(value) === JSON.stringify(defaults[key]))
        delete merged[key]
    }
    return merged
  })
  return (next ?? spec) as VideoSpec
}

/** A block whose presence means "on" (the watermark, the overlay text): `null` removes
 *  it. Written in full rather than pruned, because an empty block is not the same as
 *  no block. */
export function setChromeBlock(
  spec: VideoSpec,
  key: 'watermark' | 'overlay_text',
  block: Obj | null
): VideoSpec {
  const chrome: Obj = { ...(spec.chrome ?? {}) }
  if (block === null) delete chrome[key]
  else chrome[key] = block
  const next: Obj = { ...spec }
  if (Object.keys(chrome).length > 0) next.chrome = chrome
  else delete next.chrome
  return next as VideoSpec
}

export const STYLE_DEFAULTS = {
  background: { type: 'gradient', colors: ['#1e293b', '#0f172a'], angle: 135 },
  fit: 'blur',
  transition: { style: 'none', duration: 0.6 },
  minSceneSeconds: 2.5,
  cards: { seconds: 3.5, motion: false },
  cardText: { title_pct: 6.8, subtitle_pct: 2.9 },
  quote: {
    position: 'center',
    size_pct: 4.2,
    color: '#ffffff',
    accent: '#818cf8',
    scrim: 0.55,
  },
  code: { position: 'center', size_pct: 3.4, color: '#e2e8f0', scrim: 0.72 },
} as const

export const WATERMARK_DEFAULTS = {
  text: '',
  position: 'bottom-right',
  opacity: 0.85,
  scale_pct: 6,
  caption_pct: 2.3,
  margin_pct: 4,
} as const

export const OVERLAY_TEXT_DEFAULTS = {
  mode: 'fixed',
  text: '',
  position: 'bottom-left',
  color: '#ffffff',
  size_pct: 3,
  margin_pct: 5,
  shadow: true,
} as const

/** A scene's say over the project-wide overlays: on, off, or the default (`undefined`). */
export function setSceneChrome(
  spec: VideoSpec,
  index: number,
  chrome: boolean | undefined
) {
  return {
    ...spec,
    segments: spec.segments.map((segment, i) => {
      if (i !== index) return segment
      const next = { ...segment }
      if (chrome === undefined) delete next.chrome
      else next.chrome = chrome
      return next
    }),
  }
}

/** Whether anything is drawn project-wide, which is when a scene's opt-out means something. */
export function hasProjectOverlays(spec: VideoSpec): boolean {
  const chrome = spec.chrome
  return Boolean(chrome?.watermark || chrome?.overlay_text || chrome?.waveform)
}
