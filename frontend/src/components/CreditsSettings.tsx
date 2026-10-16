import type { Credits, VideoSpec } from '@/api/projects'
import { setCredits } from '@/spec/overlays'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

const DEFAULTS: Credits = { auto: true, card: true, description: true, extra: [] }

/**
 * The end credits. The lines are each GAM asset's credit, worked out when the video
 * renders (the library is where a credit is corrected, once, for every video using
 * it), followed by any written here.
 */
export default function CreditsSettings({ spec, onChange }: Props) {
  const credits = spec.credits ?? null
  const on = credits !== null
  const value = { ...DEFAULTS, ...(credits ?? {}) }
  const set = (patch: Partial<Credits>) =>
    onChange(setCredits(spec, { ...value, ...patch }))

  return (
    <section aria-label="Credits" className="card space-y-2 p-3 text-sm">
      <label className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => onChange(setCredits(spec, e.target.checked ? DEFAULTS : null))}
        />
        Credits
      </label>
      {on && (
        <div className="space-y-2 pl-6 text-gray-700 dark:text-gray-300">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={value.auto}
              onChange={(e) => set({ auto: e.target.checked })}
            />
            Credit the library&apos;s pictures, footage and music
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={value.card}
              onChange={(e) => set({ card: e.target.checked })}
            />
            Show them on a card at the end
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={value.description}
              onChange={(e) => set({ description: e.target.checked })}
            />
            Put them in the description
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">More lines, one per line</span>
            <textarea
              className="input mt-1 h-20 w-full"
              aria-label="More credit lines"
              value={(value.extra ?? []).join('\n')}
              onChange={(e) => set({ extra: e.target.value.split('\n') })}
              onBlur={(e) =>
                set({
                  extra: e.target.value
                    .split('\n')
                    .map((l) => l.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
        </div>
      )}
    </section>
  )
}
