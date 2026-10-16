import { Film, ImageOff, Search, X } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import type { Segment, VideoSpec } from '@/api/projects'
import { clock } from '@/spec/footage'

interface Props {
  spec: VideoSpec
  segment: Segment
  gamAssets: Record<string, GamAsset | null>
  onFind: () => void
  onRemove: () => void
}

interface Shown {
  name: string
  thumb: string | null
  /** Why there is no picture to show yet, when there isn't. */
  note?: string
}

/** What a segment's visual is, in words a person can check at a glance. */
function describe(spec: VideoSpec, key: string, gamAssets: Props['gamAssets']): Shown {
  const ref = spec.assets?.[key]
  if (!ref) return { name: key, thumb: null, note: 'Not in this project’s assets' }
  const fromGam = (id: string, label?: string): Shown => {
    if (!(id in gamAssets)) return { name: label ?? id, thumb: null }
    const asset = gamAssets[id]
    if (!asset)
      return { name: label ?? id, thumb: null, note: 'No longer in the library' }
    if (asset.missing)
      return { name: asset.name, thumb: null, note: 'Its file is missing in GAM' }
    return { name: asset.name, thumb: asset.thumb_url }
  }
  switch (ref.from) {
    case 'gam':
      return fromGam(ref.id, ref.label)
    case 'search':
      return ref.result
        ? fromGam(ref.result.id, ref.label)
        : { name: ref.label ?? ref.query, thumb: null, note: `To find: “${ref.query}”` }
    case 'notes':
      return {
        name: ref.label ?? ref.url.split('/').pop() ?? key,
        thumb: null,
        note: 'Still in the note',
      }
    case 'generate':
      return {
        name: ref.label ?? 'To generate',
        thumb: null,
        note: `To generate: “${ref.prompt}”`,
      }
  }
}

/**
 * The picture or footage a scene shows, with its trim, and the way to change it.
 * Cards draw their own background, so they have none.
 */
export default function VisualStrip({
  spec,
  segment,
  gamAssets,
  onFind,
  onRemove,
}: Props) {
  const visual = segment.visual
  if (!visual) {
    return (
      <button type="button" className="btn btn-ghost text-xs" onClick={onFind}>
        <Search className="mr-1 inline h-3 w-3" />
        Find footage
      </button>
    )
  }
  const shown = describe(spec, visual.asset, gamAssets)
  const trim = visual.trim
  return (
    <div
      className="flex items-center gap-3 rounded bg-gray-50 p-2 dark:bg-gray-800"
      aria-label="Picture"
    >
      {shown.thumb ? (
        <img src={shown.thumb} alt="" className="h-12 w-20 rounded object-cover" />
      ) : (
        <span className="flex h-12 w-20 items-center justify-center rounded bg-gray-200 dark:bg-gray-700">
          {shown.note ? (
            <ImageOff className="h-4 w-4 text-gray-400" />
          ) : (
            <Film className="h-4 w-4 text-gray-400" />
          )}
        </span>
      )}
      <span className="min-w-0 flex-1 text-sm">
        <span className="block truncate text-gray-900 dark:text-gray-100">
          {shown.name}
        </span>
        <span className="text-xs text-gray-500">
          {trim &&
            `${clock(trim.in)}–${trim.out !== undefined ? clock(trim.out) : 'end'}`}
          {trim && shown.note && ' · '}
          {shown.note}
          {visual.audio === 'play' && ' · with its sound'}
        </span>
      </span>
      <button type="button" className="btn btn-ghost text-xs" onClick={onFind}>
        <Search className="mr-1 inline h-3 w-3" />
        Change
      </button>
      <button
        type="button"
        className="btn btn-ghost p-2"
        aria-label="Remove picture"
        onClick={onRemove}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
