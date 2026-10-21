import { useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import type { Segment, VideoSpec } from '@/api/projects'
import ClipPlayer from '@/components/ClipPlayer'
import SceneSettings from '@/components/SceneSettings'
import VisualStrip from '@/components/VisualStrip'
import { footageOf } from '@/spec/clip'
import { removeVisual } from '@/spec/footage'
import {
  addScene,
  moveSegment,
  narrationText,
  removeSegment,
  updateSegment,
  withNarrationText,
} from '@/spec/edits'
import { useAssistantStore } from '@/stores/assistant'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
  /** GAM assets the spec shows, looked up by the project store. */
  gamAssets?: Record<string, GamAsset | null>
  /** Open the footage search for the segment at this index. */
  onFindFootage?: (index: number) => void
  onGenerate?: (key: string) => void
}

const KIND_LABEL: Record<Segment['kind'], string> = {
  scene: 'Scene',
  card: 'Card',
  clip: 'Clip',
}

/**
 * The video as a list of segments, built and rearranged by hand.
 *
 * The seed of M3's storyboard: today it edits labels, card titles, narration and each
 * scene's picture or footage (found in GAM), and adds, moves and removes scenes.
 * Clicking a scene's footage opens it in a player, where its trim and length are set
 * while watching.
 */
export default function SceneList({
  spec,
  onChange,
  gamAssets = {},
  onFindFootage,
  onGenerate,
}: Props) {
  const segments = spec.segments
  // One player at a time, by segment id so it follows its scene through a reorder.
  const [playing, setPlaying] = useState<string | null>(null)
  const setFocus = useAssistantStore((s) => s.setFocus)
  const edit = (index: number, change: (s: Segment) => Segment) =>
    onChange(updateSegment(spec, index, change))

  return (
    <div className="space-y-3">
      {segments.map((segment, index) => {
        const footage = footageOf(spec, segment, gamAssets)
        return (
          <section
            key={segment.id}
            id={`scene-${segment.id}`}
            aria-label={segment.label || segment.id}
            className="card space-y-2 p-3"
            // The scene being worked on is what "this scene" means to the assistant.
            onFocusCapture={() => setFocus(segment.id)}
          >
            <div className="flex items-center gap-2">
              <span className="w-6 text-right text-xs text-gray-400">{index + 1}</span>
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                {KIND_LABEL[segment.kind]}
              </span>
              <input
                className="input flex-1"
                aria-label="Label"
                value={segment.label ?? ''}
                placeholder={segment.id}
                onChange={(e) => edit(index, (s) => ({ ...s, label: e.target.value }))}
              />
              <button
                type="button"
                className="btn btn-ghost p-2"
                aria-label="Move up"
                disabled={index === 0}
                onClick={() => onChange(moveSegment(spec, index, -1))}
              >
                <ArrowUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="btn btn-ghost p-2"
                aria-label="Move down"
                disabled={index === segments.length - 1}
                onClick={() => onChange(moveSegment(spec, index, 1))}
              >
                <ArrowDown className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="btn btn-ghost p-2"
                aria-label="Remove"
                onClick={() => onChange(removeSegment(spec, index))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>

            {segment.kind === 'card' && segment.card && (
              <input
                className="input w-full"
                aria-label="Card title"
                value={segment.card.title}
                onChange={(e) =>
                  edit(index, (s) => ({
                    ...s,
                    card: { ...s.card!, title: e.target.value },
                  }))
                }
              />
            )}

            {segment.kind !== 'card' && onFindFootage && (
              <VisualStrip
                spec={spec}
                segment={segment}
                gamAssets={gamAssets}
                onFind={() => onFindFootage(index)}
                onRemove={() => onChange(removeVisual(spec, index))}
                onOpen={footage ? () => setPlaying(segment.id) : undefined}
                onGenerate={onGenerate}
              />
            )}

            {playing === segment.id && footage && (
              <ClipPlayer
                spec={spec}
                index={index}
                segment={segment}
                asset={footage}
                onChange={onChange}
                onClose={() => setPlaying(null)}
              />
            )}

            {onFindFootage && (
              <SceneSettings
                spec={spec}
                index={index}
                segment={segment}
                gamAssets={gamAssets}
                onChange={onChange}
              />
            )}

            {segment.kind === 'scene' && (
              <textarea
                className="input min-h-[5rem] w-full"
                aria-label="Narration"
                placeholder="What is said over this scene. A blank line starts a new beat."
                value={narrationText(segment)}
                onChange={(e) => edit(index, (s) => withNarrationText(s, e.target.value))}
              />
            )}

            {segment.kind === 'clip' && (
              <p className="text-xs text-gray-500">
                Plays its own sound; nothing is narrated over it.
              </p>
            )}

            <div className="flex justify-end">
              <button
                type="button"
                className="btn btn-ghost text-xs"
                onClick={() => onChange(addScene(spec, index))}
              >
                <Plus className="mr-1 inline h-3 w-3" />
                Scene after this
              </button>
            </div>
          </section>
        )
      })}

      <button
        type="button"
        className="btn btn-secondary w-full"
        onClick={() => onChange(addScene(spec))}
      >
        <Plus className="mr-1 inline h-4 w-4" />
        Add a scene
      </button>
    </div>
  )
}
