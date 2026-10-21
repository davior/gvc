import { useEffect, useRef, useState } from 'react'
import { Play, X } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import type { Segment, Trim, VideoSpec } from '@/api/projects'
import {
  assetLength,
  footageSeconds,
  nudge,
  playWindow,
  setLength,
  setLoop,
  setTrim,
  timingNote,
  trimAt,
} from '@/spec/clip'
import { clock } from '@/spec/footage'

interface Props {
  spec: VideoSpec
  index: number
  segment: Segment
  asset: GamAsset
  onChange: (next: VideoSpec) => void
  onClose: () => void
}

/** Clock time with tenths: a trim is set to the tenth, so it is shown to the tenth. */
function fine(seconds: number): string {
  const tenths = Math.round(seconds * 10)
  return `${clock(Math.floor(tenths / 10))}.${tenths % 10}`
}

const STEPS = [-1, -0.1, 0.1, 1]

/**
 * A scene's footage, played as the video will play it, and its timing set while
 * watching: in and out points, how long the scene runs, and what short footage does.
 *
 * The player stops at the out point itself rather than through a `#t=` fragment,
 * which browsers stop honouring once you seek. Muted unless the scene plays the
 * footage's own sound, so what you hear is what the video will have.
 */
export default function ClipPlayer({
  spec,
  index,
  segment,
  asset,
  onChange,
  onClose,
}: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const [now, setNow] = useState(0)
  const visual = segment.visual
  const trim = visual?.trim
  const length = assetLength(asset)
  const span = playWindow(asset, trim)
  const offset = span.start - (trim?.in ?? 0)
  const footage = footageSeconds(asset, trim)
  const fixed = segment.duration?.fixed
  const note = timingNote(spec, index, asset)
  const isVideo = asset.asset_type === 'video'

  // Jump to the new in point whenever it moves, so a nudge is seen at once.
  useEffect(() => {
    if (video.current) video.current.currentTime = span.start
  }, [span.start])

  if (!visual) return null

  function play() {
    const el = video.current
    if (!el) return
    el.currentTime = span.start
    void el.play()?.catch(() => {})
  }

  function onTime() {
    const el = video.current
    if (!el) return
    setNow(Math.max(0, el.currentTime - offset))
    if (span.end !== null && el.currentTime >= span.end) el.pause()
  }

  const change = (next: Trim | undefined) => onChange(setTrim(spec, index, next))

  const edge = (which: 'in' | 'out') => (
    <div className="flex flex-wrap items-center gap-1">
      <span className="w-8">{which === 'in' ? 'In' : 'Out'}</span>
      <span className="w-16 font-mono" aria-label={`${which} point`}>
        {which === 'in'
          ? fine(trim?.in ?? 0)
          : trim?.out !== undefined
            ? fine(trim.out)
            : length !== null
              ? fine(length)
              : 'end'}
      </span>
      {STEPS.map((step) => (
        <button
          key={step}
          type="button"
          className="btn btn-ghost px-1.5 py-0.5 text-xs"
          aria-label={`${which} ${step > 0 ? '+' : ''}${step} s`}
          onClick={() => change(nudge(trim, which, step, length))}
        >
          {step > 0 ? '+' : ''}
          {step}
        </button>
      ))}
      <button
        type="button"
        className="btn btn-secondary px-2 py-0.5 text-xs"
        onClick={() => change(trimAt(trim, which, now, length))}
      >
        Set {which} here
      </button>
    </div>
  )

  return (
    <div
      className="space-y-2 rounded border border-gray-200 p-2 text-xs text-gray-600 dark:border-gray-700 dark:text-gray-300"
      aria-label="Footage player"
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-medium text-gray-900 dark:text-gray-100">
          {asset.name}
        </span>
        <button
          type="button"
          className="btn btn-ghost p-1"
          aria-label="Close player"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {isVideo ? (
        <video
          ref={video}
          src={asset.file_url ?? undefined}
          controls
          playsInline
          preload="metadata"
          muted={visual.audio !== 'play'}
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = span.start
          }}
          onTimeUpdate={onTime}
          className="max-h-72 w-full rounded bg-black"
        />
      ) : (
        <img
          src={asset.file_url ?? asset.thumb_url ?? undefined}
          alt=""
          className="max-h-72 w-full rounded object-contain"
        />
      )}
      {isVideo && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn btn-primary px-2 py-1 text-xs"
              onClick={play}
            >
              <Play className="mr-1 inline h-3 w-3" />
              Play segment
            </button>
            <span className="font-mono">at {fine(now)}</span>
            {footage !== null && (
              <span>· {Math.round(footage * 10) / 10} s of footage</span>
            )}
            {trim && (
              <button
                type="button"
                className="btn btn-ghost px-2 py-0.5 text-xs"
                onClick={() => change(undefined)}
              >
                Whole clip
              </button>
            )}
          </div>
          {edge('in')}
          {edge('out')}
        </>
      )}
      {segment.kind === 'scene' && (
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1">
            Scene length
            <select
              className="input w-auto py-0.5"
              aria-label="Scene length"
              value={fixed !== undefined ? 'fixed' : 'narration'}
              onChange={(e) =>
                onChange(
                  setLength(
                    spec,
                    index,
                    e.target.value === 'fixed' ? (footage ?? 5) : undefined
                  )
                )
              }
            >
              <option value="narration">Follow narration</option>
              <option value="fixed">Fixed</option>
            </select>
          </label>
          {fixed !== undefined && (
            <input
              type="number"
              min="0.1"
              step="0.1"
              aria-label="Scene length in seconds"
              className="input w-20 py-0.5"
              value={fixed}
              onChange={(e) => {
                const n = Number(e.target.value)
                if (n > 0) onChange(setLength(spec, index, n))
              }}
            />
          )}
          {isVideo && footage !== null && fixed !== footage && (
            <button
              type="button"
              className="btn btn-ghost px-2 py-0.5 text-xs"
              onClick={() => onChange(setLength(spec, index, footage))}
            >
              Match footage
            </button>
          )}
          {isVideo && (
            <label className="flex items-center gap-1">
              When shorter
              <select
                className="input w-auto py-0.5"
                aria-label="When the footage is shorter"
                value={visual.loop === false ? 'hold' : 'loop'}
                onChange={(e) =>
                  onChange(setLoop(spec, index, e.target.value === 'loop'))
                }
              >
                <option value="loop">Loop</option>
                <option value="hold">Hold last frame</option>
              </select>
            </label>
          )}
        </div>
      )}
      {note && (
        <p role="status" className="text-amber-700 dark:text-amber-400">
          {note}
        </p>
      )}
    </div>
  )
}
