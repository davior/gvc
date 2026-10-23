import type { VideoSpec } from '@/api/projects'
import { DEFAULT_MOTION_AMOUNT, PROJECT_MOTIONS, setProjectMotion } from '@/spec/scene'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

/**
 * What every scene follows unless it says otherwise. Without this, a scene's
 * "Project default" camera named a setting nothing in the editor could change, and
 * the spec's own default is no move at all.
 */
export default function ProjectDefaults({ spec, onChange }: Props) {
  const motion = spec.style?.motion
  const effect = motion?.effect ?? 'none'

  return (
    <section
      aria-label="Project defaults"
      className="card flex flex-wrap items-center gap-2 p-3 text-xs text-gray-600 dark:text-gray-300"
    >
      <span className="font-medium text-gray-900 dark:text-gray-100">
        For every scene
      </span>
      <label className="flex items-center gap-1">
        Camera
        <select
          className="input w-auto py-0.5"
          aria-label="Default Ken Burns move"
          value={effect}
          onChange={(e) =>
            onChange(
              setProjectMotion(spec, {
                effect: e.target.value,
                ...(motion?.amount !== undefined ? { amount: motion.amount } : {}),
              })
            )
          }
        >
          {PROJECT_MOTIONS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
      {effect !== 'none' && (
        <label className="flex items-center gap-1">
          by
          <input
            type="number"
            min="0.02"
            max="0.5"
            step="0.01"
            aria-label="Default Ken Burns amount"
            className="input w-16 py-0.5"
            placeholder={String(DEFAULT_MOTION_AMOUNT)}
            value={motion?.amount ?? ''}
            onChange={(e) =>
              onChange(
                setProjectMotion(spec, {
                  effect,
                  ...(e.target.value ? { amount: Number(e.target.value) } : {}),
                })
              )
            }
          />
        </label>
      )}
      <span className="text-gray-500">
        Scenes with a camera move of their own keep it.
      </span>
    </section>
  )
}
