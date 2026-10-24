import { useState } from 'react'
import type { GamAsset } from '@/api/gam'
import type { Fit, VideoSpec } from '@/api/projects'
import FootageSearch from '@/components/FootageSearch'
import {
  ColourField,
  Group,
  NumberField,
  Row,
  SelectField,
} from '@/components/SettingsFields'
import { withGamAsset } from '@/spec/footage'
import { STYLE_DEFAULTS, patchSetting } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  gamAssets: Record<string, GamAsset | null>
  onChange: (next: VideoSpec) => void
}

const BACKGROUNDS = [
  { value: 'gradient', label: 'Gradient' },
  { value: 'solid', label: 'One colour' },
  { value: 'image', label: 'A picture' },
] as const

const FITS: { value: Fit; label: string }[] = [
  { value: 'blur', label: 'Whole picture over a blurred copy' },
  { value: 'pad', label: 'Whole picture with black bars' },
  { value: 'crop', label: 'Fill the frame, trim the edges' },
]

/**
 * What is behind and around a scene's picture: the background a scene without a
 * picture shows, how a picture of the wrong shape is fitted, and the shortest a scene
 * may be.
 */
export default function LookSettings({ spec, gamAssets, onChange }: Props) {
  const [picking, setPicking] = useState(false)
  const bg = { ...STYLE_DEFAULTS.background, ...(spec.style?.background ?? {}) }
  // `from` is the spec with a just-picked picture already registered in its assets.
  const setBg = (patch: Record<string, unknown>, from: VideoSpec = spec) =>
    onChange(
      patchSetting(from, ['style', 'background'], patch, STYLE_DEFAULTS.background)
    )
  const colours = [...bg.colors]
  const setColour = (i: number, value: string) => {
    colours[i] = value
    setBg({ colors: colours })
  }
  const ref = bg.asset ? spec.assets?.[bg.asset] : undefined
  const pictureName =
    (ref?.from === 'gam' && gamAssets[ref.id]?.name) || ref?.label || bg.asset

  return (
    <Group label="Look" heading="Backgrounds and fitting">
      <Row>
        <SelectField
          label="Background"
          value={bg.type}
          options={BACKGROUNDS}
          onChange={(type) => setBg({ type })}
        />
        {bg.type === 'gradient' && (
          <>
            <ColourField
              label="From colour"
              value={colours[0]}
              onChange={(v) => setColour(0, v)}
            />
            <ColourField
              label="To colour"
              value={colours[1] ?? colours[0]}
              onChange={(v) => setColour(1, v)}
            />
            <NumberField
              label="Gradient angle"
              value={bg.angle}
              min={0}
              max={360}
              suffix="°"
              onCommit={(angle) => setBg({ angle: Math.round(angle) })}
            />
          </>
        )}
        {bg.type === 'solid' && (
          <ColourField
            label="Colour"
            value={colours[0]}
            onChange={(v) => setColour(0, v)}
          />
        )}
        {bg.type === 'image' && (
          <>
            <span>{pictureName ?? 'No picture yet, so the gradient shows'}</span>
            <button
              type="button"
              className="btn btn-ghost text-xs"
              onClick={() => setPicking(true)}
            >
              {bg.asset ? 'Change picture' : 'Choose a picture'}
            </button>
          </>
        )}
      </Row>
      <Row>
        <SelectField
          label="Fit pictures"
          value={spec.style?.fit ?? STYLE_DEFAULTS.fit}
          options={FITS}
          onChange={(fit) =>
            onChange(patchSetting(spec, ['style'], { fit }, { fit: STYLE_DEFAULTS.fit }))
          }
        />
        <NumberField
          label="Shortest scene"
          value={spec.style?.min_segment_seconds ?? STYLE_DEFAULTS.minSceneSeconds}
          min={0.5}
          max={30}
          step={0.5}
          suffix="s"
          onCommit={(min_segment_seconds) =>
            onChange(
              patchSetting(
                spec,
                ['style'],
                { min_segment_seconds },
                { min_segment_seconds: STYLE_DEFAULTS.minSceneSeconds }
              )
            )
          }
        />
      </Row>
      {picking && (
        <FootageSearch
          title="A background picture"
          purpose="picture"
          initialType="image"
          onClose={() => setPicking(false)}
          onPick={(hit) => {
            const [withAsset, key] = withGamAsset(spec, hit.asset)
            setBg({ type: 'image', asset: key }, withAsset)
            setPicking(false)
          }}
        />
      )}
    </Group>
  )
}
