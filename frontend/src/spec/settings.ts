import type { VideoSpec, Waveform } from '@/api/projects'

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
