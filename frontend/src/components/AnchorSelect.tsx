import type { Anchor } from '@/api/projects'
import { anchorFrom, anchorValue, offsetOf, type AnchorOption } from '@/spec/anchors'

interface Props {
  label: string
  value: Anchor | undefined
  options: AnchorOption[]
  onPick: (next: Anchor | undefined) => void
  /** The label of the empty choice; none offered when absent. */
  noneLabel?: string
}

/**
 * Where something starts or stops: a scene's (or a line's) start or end, with an
 * offset in seconds. Anchored to the structure rather than to a time, so rewording a
 * scene moves everything placed against it along with it.
 */
export default function AnchorSelect({
  label,
  value,
  options,
  onPick,
  noneLabel,
}: Props) {
  return (
    <label className="flex items-center gap-1">
      {label}
      <select
        className="input w-auto py-0.5"
        aria-label={label}
        value={anchorValue(value)}
        onChange={(e) => onPick(anchorFrom(e.target.value, offsetOf(value)))}
      >
        {noneLabel !== undefined && <option value="">{noneLabel}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {value !== undefined && typeof value !== 'string' && (
        <input
          type="number"
          step="0.5"
          aria-label={`${label} offset in seconds`}
          title="Seconds before (negative) or after"
          className="input w-16 py-0.5"
          value={value.offset ?? 0}
          onChange={(e) =>
            onPick({ ...value, offset: Number(e.target.value) || undefined })
          }
        />
      )}
    </label>
  )
}
