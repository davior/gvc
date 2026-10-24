import { useEffect, useState } from 'react'

/**
 * The small controls the Settings tab is made of, so each section reads as a list of
 * settings rather than of markup.
 */

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <label className="flex items-center gap-1">
      {label}
      <select
        className="input w-auto py-0.5"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/**
 * A number held to a range. The box keeps what is being typed and only passes on a
 * value inside the range, so "0.9" can be typed into a field that starts at 0.5 (the
 * "0" on its own is out of range and must not be refused or rewritten under the
 * caret). Leaving the box puts back the last accepted value.
 */
export function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  suffix,
  onCommit,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  suffix?: string
  onCommit: (value: number) => void
}) {
  const [text, setText] = useState(String(value))
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    if (!editing) setText(String(value))
  }, [value, editing])

  return (
    <label className="flex items-center gap-1">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        aria-label={label}
        className="input w-20 py-0.5"
        value={text}
        onFocus={() => setEditing(true)}
        onBlur={() => {
          setEditing(false)
          setText(String(value))
        }}
        onChange={(e) => {
          setText(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value !== '' && Number.isFinite(n) && n >= min && n <= max)
            onCommit(n)
        }}
      />
      {suffix}
    </label>
  )
}

export function ColourField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex items-center gap-1">
      {label}
      <input
        type="color"
        aria-label={label}
        className="h-6 w-8 cursor-pointer rounded"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

export function RangeField({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex items-center gap-1">
      {label}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

export function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center gap-1">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}

/** One group of settings: a heading and rows of fields. */
export function Group({
  label,
  heading,
  children,
}: {
  label: string
  heading: string
  children: React.ReactNode
}) {
  return (
    <section aria-label={label} className="card space-y-2 p-3 text-sm">
      {heading && (
        <h2 className="font-medium text-gray-900 dark:text-gray-100">{heading}</h2>
      )}
      {children}
    </section>
  )
}

export function Row({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
      {children}
    </div>
  )
}
