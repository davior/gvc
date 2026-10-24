import type { WaveMode, WavePosition, Waveform } from '@/api/projects'

// Notes' names for the wave styles, so the same wave is called the same in both.
export const WAVE_MODES: { value: WaveMode; label: string }[] = [
  { value: 'line', label: 'Line' },
  { value: 'cline', label: 'Centred line' },
  { value: 'p2p', label: 'Peak to peak' },
  { value: 'point', label: 'Points' },
]

export const WAVE_POSITIONS: { value: WavePosition; label: string }[] = [
  { value: 'top', label: 'Top' },
  { value: 'center', label: 'Centre' },
  { value: 'bottom', label: 'Bottom' },
]

/** The same defaults as the waveform in Gecko Notes' video dialog. Written out in full
 *  so the controls show what is drawn rather than a blank that means "the default". */
export const DEFAULT_WAVEFORM: Required<Waveform> = {
  mode: 'line',
  color: '#00ff41',
  opacity: 0.7,
  position: 'bottom',
  height_pct: 22,
  scrim: 0.45,
}
