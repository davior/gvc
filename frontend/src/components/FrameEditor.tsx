import { useRef, useState, type PointerEvent } from 'react'
import type { Frame } from '@/api/projects'
import { clampFrame } from '@/spec/scene'

interface Props {
  imageUrl: string | null
  /** The picture's width over its height. */
  pictureAspect: number
  /** The video's width over its height. */
  outputAspect: number
  from: Frame
  to: Frame
  onChange: (next: { from: Frame; to: Frame }) => void
}

type Which = 'from' | 'to'

const COLOURS: Record<Which, string> = { from: '#22c55e', to: '#ef4444' }
const NAMES: Record<Which, string> = { from: 'Start', to: 'End' }

/**
 * Where a Ken Burns move starts and ends, as two boxes over the picture.
 *
 * Drag a box to move it; drag its corner to make it bigger or smaller. Its shape is
 * the video's, so a frame can never ask for a stretched picture (the spec stores only
 * its width). The numbers underneath are the same frames, for exact positions.
 */
export default function FrameEditor({
  imageUrl,
  pictureAspect,
  outputAspect,
  from,
  to,
  onChange,
}: Props) {
  const area = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{
    which: Which
    mode: 'move' | 'size'
    startX: number
    startY: number
    frame: Frame
  } | null>(null)
  // A frame's height as a fraction of the picture's, per unit of its width.
  const heightPerWidth = pictureAspect / outputAspect
  const frames = { from, to }

  function set(which: Which, frame: Frame) {
    const next = { ...frames, [which]: clampFrame(frame, heightPerWidth) }
    onChange(next)
  }

  function begin(which: Which, mode: 'move' | 'size', event: PointerEvent) {
    event.preventDefault()
    event.stopPropagation()
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
    setDrag({
      which,
      mode,
      startX: event.clientX,
      startY: event.clientY,
      frame: frames[which],
    })
  }

  function move(event: PointerEvent) {
    if (!drag || !area.current) return
    const box = area.current.getBoundingClientRect()
    const dx = (event.clientX - drag.startX) / box.width
    const dy = (event.clientY - drag.startY) / box.height
    const f = drag.frame
    set(
      drag.which,
      drag.mode === 'move' ? { ...f, x: f.x + dx, y: f.y + dy } : { ...f, w: f.w + dx }
    )
  }

  return (
    <div className="space-y-2" aria-label="Ken Burns frames">
      <div
        ref={area}
        className="relative w-full select-none overflow-hidden rounded bg-gray-200 dark:bg-gray-700"
        style={{ aspectRatio: String(pictureAspect) }}
        onPointerMove={move}
        onPointerUp={() => setDrag(null)}
      >
        {imageUrl && (
          <img
            src={imageUrl}
            alt=""
            className="absolute inset-0 h-full w-full"
            draggable={false}
          />
        )}
        {(['from', 'to'] as Which[]).map((which) => {
          const f = frames[which]
          return (
            <div
              key={which}
              role="button"
              aria-label={`${NAMES[which]} frame`}
              className="absolute cursor-move border-2"
              style={{
                left: `${f.x * 100}%`,
                top: `${f.y * 100}%`,
                width: `${f.w * 100}%`,
                height: `${Math.min(1, f.w * heightPerWidth) * 100}%`,
                borderColor: COLOURS[which],
                background: `${COLOURS[which]}22`,
              }}
              onPointerDown={(e) => begin(which, 'move', e)}
            >
              <span
                className="absolute left-1 top-0.5 text-[10px] font-semibold"
                style={{ color: COLOURS[which] }}
              >
                {NAMES[which]}
              </span>
              <span
                aria-label={`Resize ${NAMES[which].toLowerCase()} frame`}
                className="absolute -bottom-1 -right-1 h-3 w-3 cursor-nwse-resize rounded-sm"
                style={{ background: COLOURS[which] }}
                onPointerDown={(e) => begin(which, 'size', e)}
              />
            </div>
          )
        })}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        {(['from', 'to'] as Which[]).map((which) => (
          <fieldset key={which} className="flex items-center gap-1">
            <legend className="sr-only">{NAMES[which]} frame</legend>
            <span className="w-8 font-medium" style={{ color: COLOURS[which] }}>
              {NAMES[which]}
            </span>
            {(['x', 'y', 'w'] as const).map((field) => (
              <label key={field} className="flex items-center gap-0.5">
                {field}
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  aria-label={`${NAMES[which]} ${field}`}
                  className="input w-16 px-1 py-0.5"
                  value={frames[which][field]}
                  onChange={(e) =>
                    set(which, { ...frames[which], [field]: Number(e.target.value) })
                  }
                />
              </label>
            ))}
          </fieldset>
        ))}
      </div>
    </div>
  )
}
