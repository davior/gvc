import type { VideoSpec, WaveMode, WavePosition, Waveform } from '@/api/projects'
import { setWaveform } from '@/spec/settings'
import { DEFAULT_WAVEFORM, WAVE_MODES, WAVE_POSITIONS } from '@/spec/waveform'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

/**
 * An animated audio wave drawn across every scene, as Notes does for a whole video.
 * Its settings are those of a scene's own wave. A scene that wants one only for
 * itself, or for part of itself, adds the wave as a layer instead.
 */
export default function WaveformSettings({ spec, onChange }: Props) {
  const wave = spec.chrome?.waveform ?? null
  const value = { ...DEFAULT_WAVEFORM, ...(wave ?? {}) }
  const set = (patch: Waveform) => onChange(setWaveform(spec, { ...value, ...patch }))

  return (
    <section aria-label="Audio wave" className="card space-y-2 p-3 text-sm">
      <label className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
        <input
          type="checkbox"
          checked={wave !== null}
          onChange={(e) => onChange(setWaveform(spec, e.target.checked ? value : null))}
        />
        Animated audio wave on every scene
      </label>
      {wave !== null && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
          <label className="flex items-center gap-1">
            Style
            <select
              className="input w-auto py-0.5"
              aria-label="Wave style"
              value={value.mode}
              onChange={(e) => set({ mode: e.target.value as WaveMode })}
            >
              {WAVE_MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            Where
            <select
              className="input w-auto py-0.5"
              aria-label="Wave position"
              value={value.position}
              onChange={(e) => set({ position: e.target.value as WavePosition })}
            >
              {WAVE_POSITIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <input
            type="color"
            aria-label="Wave colour"
            className="h-6 w-8 cursor-pointer rounded"
            value={value.color}
            onChange={(e) => set({ color: e.target.value })}
          />
          <label className="flex items-center gap-1">
            Height
            <input
              type="range"
              min="8"
              max="50"
              step="1"
              aria-label="Wave height, % of the frame"
              value={value.height_pct}
              onChange={(e) => set({ height_pct: Number(e.target.value) })}
            />
          </label>
          <label className="flex items-center gap-1">
            Opacity
            <input
              type="range"
              min="0.1"
              max="1"
              step="0.05"
              aria-label="Wave opacity"
              value={value.opacity}
              onChange={(e) => set({ opacity: Number(e.target.value) })}
            />
          </label>
          <label className="flex items-center gap-1">
            Backing
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              aria-label="Darkened backing behind the wave"
              value={value.scrim}
              onChange={(e) => set({ scrim: Number(e.target.value) })}
            />
          </label>
        </div>
      )}
    </section>
  )
}
