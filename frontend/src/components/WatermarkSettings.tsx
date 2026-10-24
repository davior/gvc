import { useState } from 'react'
import type { GamAsset } from '@/api/gam'
import type { Position, VideoSpec } from '@/api/projects'
import FootageSearch from '@/components/FootageSearch'
import {
  Group,
  NumberField,
  RangeField,
  Row,
  SelectField,
} from '@/components/SettingsFields'
import { withGamAsset } from '@/spec/footage'
import { POSITIONS } from '@/spec/positions'
import { WATERMARK_DEFAULTS, setChromeBlock } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  gamAssets: Record<string, GamAsset | null>
  onChange: (next: VideoSpec) => void
}

/**
 * A small mark in one corner of every scene: a picture from the library, a line of
 * text beside it, or either alone. Left empty, the line reads "by" and the title.
 */
export default function WatermarkSettings({ spec, gamAssets, onChange }: Props) {
  const [picking, setPicking] = useState(false)
  const mark = spec.chrome?.watermark ?? null
  const value = { ...WATERMARK_DEFAULTS, ...(mark ?? {}) }
  const set = (patch: Record<string, unknown>, from: VideoSpec = spec) =>
    onChange(setChromeBlock(from, 'watermark', { ...value, ...patch }))
  const ref = mark?.asset ? spec.assets?.[mark.asset] : undefined
  const pictureName =
    (ref?.from === 'gam' && gamAssets[ref.id]?.name) || ref?.label || mark?.asset

  return (
    <Group label="Watermark" heading="">
      <label className="flex items-center gap-2 font-medium text-gray-900 dark:text-gray-100">
        <input
          type="checkbox"
          checked={mark !== null}
          onChange={(e) =>
            onChange(setChromeBlock(spec, 'watermark', e.target.checked ? value : null))
          }
        />
        Watermark on every scene
      </label>
      {mark !== null && (
        <>
          <Row>
            <span>{pictureName ?? 'No picture'}</span>
            <button
              type="button"
              className="btn btn-ghost text-xs"
              onClick={() => setPicking(true)}
            >
              {mark.asset ? 'Change picture' : 'Choose a picture'}
            </button>
            {mark.asset && (
              <button
                type="button"
                className="btn btn-ghost text-xs"
                onClick={() => set({ asset: undefined })}
              >
                Remove picture
              </button>
            )}
            <label className="flex items-center gap-1">
              Text
              <input
                className="input w-44 py-0.5"
                aria-label="Watermark text"
                placeholder={spec.title ? `by ${spec.title}` : 'by the title'}
                value={value.text}
                onChange={(e) => set({ text: e.target.value })}
              />
            </label>
          </Row>
          <Row>
            <SelectField
              label="Watermark corner"
              value={value.position as Position}
              options={POSITIONS}
              onChange={(position) => set({ position })}
            />
            <NumberField
              label="Watermark picture size, % of the height"
              value={value.scale_pct}
              min={1}
              max={30}
              step={0.5}
              suffix="%"
              onCommit={(scale_pct) => set({ scale_pct })}
            />
            <NumberField
              label="Watermark text size, % of the height"
              value={value.caption_pct}
              min={0.5}
              max={15}
              step={0.1}
              suffix="%"
              onCommit={(caption_pct) => set({ caption_pct })}
            />
            <NumberField
              label="Watermark margin, % of the frame"
              value={value.margin_pct}
              min={0}
              max={25}
              suffix="%"
              onCommit={(margin_pct) => set({ margin_pct: Math.round(margin_pct) })}
            />
            <RangeField
              label="Watermark opacity"
              value={value.opacity}
              min={0.1}
              max={1}
              step={0.05}
              onChange={(opacity) => set({ opacity })}
            />
          </Row>
        </>
      )}
      {picking && (
        <FootageSearch
          title="A picture for the watermark"
          purpose="picture"
          initialType="image"
          onClose={() => setPicking(false)}
          onPick={(hit) => {
            const [withAsset, key] = withGamAsset(spec, hit.asset)
            set({ asset: key }, withAsset)
            setPicking(false)
          }}
        />
      )}
    </Group>
  )
}
