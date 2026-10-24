import type { VideoSpec } from '@/api/projects'
import { NumberField } from '@/components/SettingsFields'
import { VOICE_DEFAULTS, setVoice } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

const PAUSES = [
  { key: 'paragraph_ms', label: 'Between paragraphs', max: 3000 },
  { key: 'heading_ms', label: 'At a heading', max: 5000 },
  { key: 'segment_end_ms', label: 'At the end of a scene', max: 3000 },
] as const

/**
 * The narrator for the whole video. A scene's own speed (in its settings) wins over
 * this one. Left blank, the voice is whichever one the account is set to in Notes;
 * naming one pins it, and it has to be a name that account's speech engine knows.
 */
export default function VoiceSettings({ spec, onChange }: Props) {
  const voice = spec.voice
  const pauses = { ...VOICE_DEFAULTS.pauses, ...(voice?.pauses ?? {}) }

  return (
    <section aria-label="Narration" className="card space-y-2 p-3 text-sm">
      <h2 className="font-medium text-gray-900 dark:text-gray-100">Narration</h2>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
        <label className="flex items-center gap-1">
          Voice
          <input
            className="input w-40 py-0.5"
            aria-label="Narrator voice"
            placeholder="The account's voice"
            value={voice?.voice ?? ''}
            onChange={(e) => onChange(setVoice(spec, { voice: e.target.value }))}
          />
        </label>
        <NumberField
          label="Speaking speed"
          value={voice?.speed ?? VOICE_DEFAULTS.speed}
          min={0.5}
          max={2}
          step={0.05}
          suffix="×"
          onCommit={(speed) => onChange(setVoice(spec, { speed }))}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
        <span className="font-medium">Pause</span>
        {PAUSES.map((p) => (
          <NumberField
            key={p.key}
            label={`Pause ${p.label.toLowerCase()}, milliseconds`}
            value={pauses[p.key]}
            min={0}
            max={p.max}
            step={50}
            suffix="ms"
            onCommit={(ms) =>
              onChange(setVoice(spec, { pauses: { [p.key]: Math.round(ms) } }))
            }
          />
        ))}
      </div>
    </section>
  )
}
