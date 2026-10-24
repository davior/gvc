import type { VideoSpec } from '@/api/projects'
import {
  ColourField,
  Group,
  NumberField,
  RangeField,
  Row,
  SelectField,
} from '@/components/SettingsFields'
import { BANDS } from '@/spec/positions'
import { STYLE_DEFAULTS, patchSetting } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

/** Quote and code panels, which take the whole frame for a moment. */
export default function PanelSettings({ spec, onChange }: Props) {
  const quote = { ...STYLE_DEFAULTS.quote, ...(spec.style?.quote ?? {}) }
  const code = { ...STYLE_DEFAULTS.code, ...(spec.style?.code ?? {}) }
  const setQuote = (patch: Record<string, unknown>) =>
    onChange(patchSetting(spec, ['style', 'quote'], patch, STYLE_DEFAULTS.quote))
  const setCode = (patch: Record<string, unknown>) =>
    onChange(patchSetting(spec, ['style', 'code'], patch, STYLE_DEFAULTS.code))

  return (
    <Group label="Quote and code panels" heading="Quote and code panels">
      <Row>
        <span className="w-12 font-medium">Quote</span>
        <SelectField
          label="Quote position"
          value={quote.position}
          options={BANDS}
          onChange={(position) => setQuote({ position })}
        />
        <NumberField
          label="Quote text size, % of the height"
          value={quote.size_pct}
          min={1}
          max={15}
          step={0.1}
          suffix="%"
          onCommit={(size_pct) => setQuote({ size_pct })}
        />
        <ColourField
          label="Quote colour"
          value={quote.color}
          onChange={(color) => setQuote({ color })}
        />
        <ColourField
          label="Quote accent colour"
          value={quote.accent}
          onChange={(accent) => setQuote({ accent })}
        />
        <RangeField
          label="Quote backing"
          value={quote.scrim}
          min={0}
          max={1}
          step={0.05}
          onChange={(scrim) => setQuote({ scrim })}
        />
      </Row>
      <Row>
        <span className="w-12 font-medium">Code</span>
        <SelectField
          label="Code position"
          value={code.position}
          options={BANDS}
          onChange={(position) => setCode({ position })}
        />
        <NumberField
          label="Code text size, % of the height"
          value={code.size_pct}
          min={1}
          max={12}
          step={0.1}
          suffix="%"
          onCommit={(size_pct) => setCode({ size_pct })}
        />
        <ColourField
          label="Code colour"
          value={code.color}
          onChange={(color) => setCode({ color })}
        />
        <RangeField
          label="Code backing"
          value={code.scrim}
          min={0}
          max={1}
          step={0.05}
          onChange={(scrim) => setCode({ scrim })}
        />
      </Row>
    </Group>
  )
}
