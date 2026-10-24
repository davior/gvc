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
