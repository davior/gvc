import type { VideoSpec } from '@/api/projects'
import { CheckField, Group, NumberField, Row } from '@/components/SettingsFields'
import { STYLE_DEFAULTS, patchSetting } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

/** Title and chapter cards: how long they show and how big their type is. */
export default function CardSettings({ spec, onChange }: Props) {
  const cards = spec.style?.cards
  const setCards = (patch: Record<string, unknown>) =>
    onChange(patchSetting(spec, ['style', 'cards'], patch, STYLE_DEFAULTS.cards))
  const setText = (which: 'title' | 'chapter', patch: Record<string, unknown>) =>
    onChange(
      patchSetting(spec, ['style', 'cards', which], patch, STYLE_DEFAULTS.cardText)
    )

  return (
    <Group label="Title cards" heading="Title and chapter cards">
      <Row>
        <NumberField
          label="Card length"
          value={cards?.seconds ?? STYLE_DEFAULTS.cards.seconds}
          min={0.5}
          max={30}
          step={0.5}
          suffix="s"
          onCommit={(seconds) => setCards({ seconds })}
        />
        <CheckField
          label="Slow zoom on cards"
          checked={cards?.motion ?? STYLE_DEFAULTS.cards.motion}
          onChange={(motion) => setCards({ motion })}
        />
      </Row>
      {(['title', 'chapter'] as const).map((which) => {
        const text = { ...STYLE_DEFAULTS.cardText, ...(cards?.[which] ?? {}) }
        const name = which === 'title' ? 'Title card' : 'Chapter card'
        return (
          <Row key={which}>
            <span className="w-24 font-medium">{name}</span>
            <NumberField
              label={`${name} heading size, % of the height`}
              value={text.title_pct}
              min={1}
              max={25}
              step={0.1}
              suffix="%"
              onCommit={(title_pct) => setText(which, { title_pct })}
            />
            <NumberField
              label={`${name} subtitle size, % of the height`}
              value={text.subtitle_pct}
              min={0.5}
              max={15}
              step={0.1}
              suffix="%"
              onCommit={(subtitle_pct) => setText(which, { subtitle_pct })}
            />
          </Row>
        )
      })}
    </Group>
  )
}
