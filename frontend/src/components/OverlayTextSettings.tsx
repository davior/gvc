import type { OverlayText, Position, VideoSpec } from '@/api/projects'
import {
  CheckField,
  ColourField,
  Group,
  NumberField,
  Row,
  SelectField,
} from '@/components/SettingsFields'
import { POSITIONS } from '@/spec/positions'
import { OVERLAY_TEXT_DEFAULTS, setChromeBlock } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

const MODES: { value: NonNullable<OverlayText['mode']>; label: string }[] = [
  { value: 'fixed', label: 'The text below' },
  { value: 'title', label: 'The video’s title' },
  { value: 'title_chapter', label: 'Title and current chapter' },
]

/** A line of text on every scene, such as a title, a channel name or a hashtag. */
export default function OverlayTextSettings({ spec, onChange }: Props) {
  const block = spec.chrome?.overlay_text ?? null
  const value = { ...OVERLAY_TEXT_DEFAULTS, ...(block ?? {}) }
  const set = (patch: Record<string, unknown>) =>
    onChange(setChromeBlock(spec, 'overlay_text', { ...value, ...patch }))

  return (
    <Group label="Text on every scene" heading="">
      <label className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
        <input
          type="checkbox"
          checked={block !== null}
          onChange={(e) =>
            onChange(
              setChromeBlock(spec, 'overlay_text', e.target.checked ? value : null)
            )
          }
        />
        Text on every scene
      </label>
      {block !== null && (
        <>
          <Row>
            <SelectField
              label="Text shows"
              value={value.mode}
              options={MODES}
              onChange={(mode) => set({ mode })}
            />
            {value.mode === 'fixed' && (
              <label className="flex items-center gap-1">
                Text
                <input
                  className="input w-56 py-0.5"
                  aria-label="Text on every scene"
                  value={value.text}
                  onChange={(e) => set({ text: e.target.value })}
                />
              </label>
            )}
          </Row>
          <Row>
            <SelectField
              label="Text position"
              value={value.position as Position}
              options={POSITIONS}
              onChange={(position) => set({ position })}
            />
            <NumberField
              label="Text size, % of the height"
              value={value.size_pct}
              min={0.5}
              max={20}
              step={0.1}
              suffix="%"
              onCommit={(size_pct) => set({ size_pct })}
            />
            <NumberField
              label="Text margin, % of the frame"
              value={value.margin_pct}
              min={0}
              max={25}
              suffix="%"
              onCommit={(margin_pct) => set({ margin_pct: Math.round(margin_pct) })}
            />
            <ColourField
              label="Text colour"
              value={value.color}
              onChange={(color) => set({ color })}
            />
            <CheckField
              label="Shadow behind the text"
              checked={value.shadow}
              onChange={(shadow) => set({ shadow })}
            />
          </Row>
        </>
      )}
    </Group>
  )
}
