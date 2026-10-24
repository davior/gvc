import { useMemo, useState } from 'react'
import { AudioWaveform, Image as ImageIcon, Trash2, Type, UserRound } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import type {
  Overlay,
  Position,
  Segment,
  VideoSpec,
  WaveMode,
  WavePosition,
} from '@/api/projects'
import AnchorSelect from '@/components/AnchorSelect'
import { sceneName, type AnchorOption } from '@/spec/anchors'
import FootageSearch from '@/components/FootageSearch'
import {
  addImageOverlay,
  addOverlay,
  addWaveOverlay,
  isTimed,
  removeOverlay,
  updateOverlay,
} from '@/spec/overlays'

interface Props {
  spec: VideoSpec
  index: number
  segment: Segment
  gamAssets: Record<string, GamAsset | null>
  onChange: (next: VideoSpec) => void
}

const POSITIONS: { value: Position; label: string }[] = [
  { value: 'top-left', label: 'Top left' },
  { value: 'top-right', label: 'Top right' },
  { value: 'center', label: 'Centre' },
  { value: 'bottom-left', label: 'Bottom left' },
  { value: 'bottom-right', label: 'Bottom right' },
]

// Notes' names for the wave styles, so the same wave is called the same in both.
const WAVE_MODES: { value: WaveMode; label: string }[] = [
  { value: 'line', label: 'Line' },
  { value: 'cline', label: 'Centred line' },
  { value: 'p2p', label: 'Peak to peak' },
  { value: 'point', label: 'Points' },
]

const WAVE_POSITIONS: { value: WavePosition; label: string }[] = [
  { value: 'top', label: 'Top' },
  { value: 'center', label: 'Centre' },
  { value: 'bottom', label: 'Bottom' },
]

const KIND_LABEL: Record<string, string> = {
  waveform: 'Wave',
  text: 'Text',
  lower_third: 'Name',
  image: 'Picture',
}

/**
 * What is drawn over a scene: text, a lower third naming who is speaking, a picture.
 *
 * Each shows for the whole scene unless told otherwise, and "from" and "until" are
 * anchored to the scene's lines or edges, never to seconds, so it stays with what it
 * is about when the narration is reworded. "Until" can reach into a later scene, which
 * is how a title is held across a transition.
 */
export default function OverlayEditor({
  spec,
  index,
  segment,
  gamAssets,
  onChange,
}: Props) {
  const [picking, setPicking] = useState(false)
  const overlays = (segment.overlays ?? []).filter(isTimed)
  const options = useMemo<AnchorOption[]>(() => {
    const beats = segment.narration?.beats ?? []
    const later = spec.segments.slice(index + 1)
    return [
      { value: 'start:', label: 'start of this scene' },
      ...beats.flatMap((b, i) => [
        { value: `start::${b.id}`, label: `start of line ${i + 1}` },
        { value: `end::${b.id}`, label: `end of line ${i + 1}` },
      ]),
      { value: 'end:', label: 'end of this scene' },
      ...later.flatMap((s, i) => [
        { value: `start:${s.id}`, label: `start of ${sceneName(s, index + 1 + i)}` },
        { value: `end:${s.id}`, label: `end of ${sceneName(s, index + 1 + i)}` },
      ]),
    ]
  }, [spec.segments, segment, index])

  const set = (id: string, patch: Partial<Overlay>) =>
    onChange(updateOverlay(spec, index, id, patch))
  const pictureName = (key: string) => {
    const ref = spec.assets?.[key]
    const id = ref?.from === 'gam' ? ref.id : undefined
    return (id && gamAssets[id]?.name) || ref?.label || key
  }

  return (
    <div className="space-y-2" aria-label="On screen">
      {overlays.map((overlay) => (
        <section
          key={overlay.id}
          aria-label={`${KIND_LABEL[overlay.type]} on screen`}
          className="space-y-1.5 rounded border border-gray-200 p-2 dark:border-gray-700"
        >
          <div className="flex items-center gap-2">
            <span className="w-14 shrink-0 font-medium text-gray-800 dark:text-gray-200">
              {KIND_LABEL[overlay.type]}
            </span>
            {overlay.type === 'text' && (
              <input
                className="input min-w-0 flex-1 py-0.5"
                aria-label="Text"
                value={overlay.text}
                onChange={(e) => set(overlay.id, { text: e.target.value })}
              />
            )}
            {overlay.type === 'lower_third' && (
              <>
                <input
                  className="input min-w-0 flex-1 py-0.5"
                  aria-label="Name"
                  value={overlay.title}
                  onChange={(e) => set(overlay.id, { title: e.target.value })}
                />
                <input
                  className="input min-w-0 flex-1 py-0.5"
                  aria-label="Role"
                  placeholder="Role (optional)"
                  value={overlay.subtitle ?? ''}
                  onChange={(e) =>
                    set(overlay.id, { subtitle: e.target.value || undefined })
                  }
                />
              </>
            )}
            {overlay.type === 'image' && (
              <span className="min-w-0 flex-1 truncate">
                {pictureName(overlay.asset)}
              </span>
            )}
            {overlay.type === 'waveform' && (
              <span className="min-w-0 flex-1 truncate text-gray-500">
                Moves with the sound
              </span>
            )}
            <button
              type="button"
              className="btn btn-ghost p-1"
              aria-label="Remove from screen"
              onClick={() => onChange(removeOverlay(spec, index, overlay.id))}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {(overlay.type === 'text' || overlay.type === 'image') && (
              <label className="flex items-center gap-1">
                Where
                <select
                  className="input w-auto py-0.5"
                  aria-label="Position"
                  value={overlay.position ?? 'center'}
                  onChange={(e) =>
                    set(overlay.id, { position: e.target.value as Position })
                  }
                >
                  {POSITIONS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {overlay.type === 'text' && (
              <>
                <label className="flex items-center gap-1">
                  Size
                  <input
                    type="number"
                    min="1"
                    max="25"
                    step="0.5"
                    aria-label="Text size, % of the height"
                    className="input w-14 py-0.5"
                    placeholder="6"
                    value={overlay.size_pct ?? ''}
                    onChange={(e) =>
                      set(overlay.id, {
                        size_pct: e.target.value ? Number(e.target.value) : undefined,
                      })
                    }
                  />
                </label>
                <input
                  type="color"
                  aria-label="Text colour"
                  className="h-6 w-8 cursor-pointer rounded"
                  value={overlay.color ?? '#ffffff'}
                  onChange={(e) => set(overlay.id, { color: e.target.value })}
                />
              </>
            )}
            {overlay.type === 'image' && (
              <>
                <label className="flex items-center gap-1">
                  Width
                  <input
                    type="number"
                    min="1"
                    max="100"
                    step="1"
                    aria-label="Picture width, % of the frame"
                    className="input w-14 py-0.5"
                    placeholder="30"
                    value={overlay.scale_pct ?? ''}
                    onChange={(e) =>
                      set(overlay.id, {
                        scale_pct: e.target.value ? Number(e.target.value) : undefined,
                      })
                    }
                  />
                  %
                </label>
                <label className="flex items-center gap-1">
                  Opacity
                  <input
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                    aria-label="Picture opacity"
                    value={overlay.opacity ?? 1}
                    onChange={(e) => set(overlay.id, { opacity: Number(e.target.value) })}
                  />
                </label>
              </>
            )}
            {overlay.type === 'waveform' && (
              <>
                <label className="flex items-center gap-1">
                  Style
                  <select
                    className="input w-auto py-0.5"
                    aria-label="Wave style"
                    value={overlay.mode ?? 'line'}
                    onChange={(e) =>
                      set(overlay.id, { mode: e.target.value as WaveMode })
                    }
                  >
                    {WAVE_MODES.map((m) => (
                      <option key={m.value} value={m.value}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1">
                  Where
                  <select
                    className="input w-auto py-0.5"
                    aria-label="Wave position"
                    value={overlay.position ?? 'bottom'}
                    onChange={(e) =>
                      set(overlay.id, { position: e.target.value as WavePosition })
                    }
                  >
                    {WAVE_POSITIONS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </label>
                <input
                  type="color"
                  aria-label="Wave colour"
                  className="h-6 w-8 cursor-pointer rounded"
                  value={overlay.color ?? '#00ff41'}
                  onChange={(e) => set(overlay.id, { color: e.target.value })}
                />
                <label className="flex items-center gap-1">
                  Height
                  <input
                    type="range"
                    min="8"
                    max="50"
                    step="1"
                    aria-label="Wave height, % of the frame"
                    value={overlay.height_pct ?? 22}
                    onChange={(e) =>
                      set(overlay.id, { height_pct: Number(e.target.value) })
                    }
                  />
                </label>
                <label className="flex items-center gap-1">
                  Opacity
                  <input
                    type="range"
                    min="0.1"
                    max="1"
                    step="0.05"
                    aria-label="Wave opacity"
                    value={overlay.opacity ?? 0.7}
                    onChange={(e) => set(overlay.id, { opacity: Number(e.target.value) })}
                  />
                </label>
                <label className="flex items-center gap-1">
                  Backing
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    aria-label="Darkened backing behind the wave"
                    value={overlay.scrim ?? 0.45}
                    onChange={(e) => set(overlay.id, { scrim: Number(e.target.value) })}
                  />
                </label>
              </>
            )}
            <label className="flex items-center gap-1">
              Fade
              <input
                type="number"
                min="0"
                max="5"
                step="0.1"
                aria-label="Fade in and out, seconds"
                className="input w-14 py-0.5"
                placeholder="0.3"
                value={overlay.fade ?? ''}
                onChange={(e) =>
                  set(overlay.id, {
                    fade: e.target.value === '' ? undefined : Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <AnchorSelect
              label="From"
              value={overlay.show?.from}
              options={options}
              noneLabel="the whole scene"
              onPick={(from) =>
                set(overlay.id, {
                  show: from
                    ? { from, to: overlay.show?.to ?? { edge: 'end' } }
                    : undefined,
                })
              }
            />
            {overlay.show && (
              <AnchorSelect
                label="Until"
                value={overlay.show.to}
                options={options}
                onPick={(to) => to && set(overlay.id, { show: { ...overlay.show!, to } })}
              />
            )}
          </div>
        </section>
      ))}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-ghost text-xs"
          onClick={() => onChange(addOverlay(spec, index, 'text'))}
        >
          <Type className="mr-1 inline h-3.5 w-3.5" />
          Text
        </button>
        <button
          type="button"
          className="btn btn-ghost text-xs"
          onClick={() => onChange(addOverlay(spec, index, 'lower_third'))}
        >
          <UserRound className="mr-1 inline h-3.5 w-3.5" />
          Name and role
        </button>
        <button
          type="button"
          className="btn btn-ghost text-xs"
          onClick={() => setPicking(true)}
        >
          <ImageIcon className="mr-1 inline h-3.5 w-3.5" />
          Picture
        </button>
        <button
          type="button"
          className="btn btn-ghost text-xs"
          onClick={() => onChange(addWaveOverlay(spec, index))}
        >
          <AudioWaveform className="mr-1 inline h-3.5 w-3.5" />
          Audio wave
        </button>
      </div>
      {picking && (
        <FootageSearch
          title="A picture to put on screen"
          purpose="overlay"
          initialType="image"
          onClose={() => setPicking(false)}
          onPick={(hit) => {
            onChange(addImageOverlay(spec, index, hit.asset))
            setPicking(false)
          }}
        />
      )}
    </div>
  )
}
