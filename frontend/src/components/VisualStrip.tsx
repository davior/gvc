import { Film, ImageOff, Search, Sparkles, Square, X } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import { RUNNING, type Generation } from '@/api/generations'
import type { Segment, VideoSpec } from '@/api/projects'
import { clock } from '@/spec/footage'
import { latestByKey } from '@/spec/generation'
import { useGenerationStore } from '@/stores/generations'

interface Props {
  spec: VideoSpec
  segment: Segment
  gamAssets: Record<string, GamAsset | null>
  onFind: () => void
  onRemove: () => void
  /** Open the Generate dialog for a placeholder; absent, nothing offers to. */
  onGenerate?: (key: string) => void
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
      return ref.result
        ? fromGam(ref.result.id, ref.label)
        : {
            name: ref.label ?? 'To generate',
            thumb: null,
            note: `To generate: “${ref.prompt}”`,
          }
  }
}

/** Where a running generation has got to, in a few words. */
function progressOf(row: Generation): string {
  const stage = row.stage || (row.status === 'queued' ? 'Waiting to start' : 'Generating')
  return row.detail ? `${stage} · ${row.detail}` : stage
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
  onGenerate,
}: Props) {
  const rows = useGenerationStore((s) => s.rows)
  const cancel = useGenerationStore((s) => s.cancel)
  const choose = useGenerationStore((s) => s.choose)
  const visual = segment.visual
  if (!visual) {
    return (
      <button type="button" className="btn btn-ghost text-xs" onClick={onFind}>
        <Search className="mr-1 inline h-3 w-3" />
        Find footage
      </button>
    )
  }
  const ref = spec.assets?.[visual.asset]
  const generated = ref?.from === 'generate' ? ref : undefined
  const row = generated ? latestByKey(rows)[visual.asset] : undefined
  const running = row && RUNNING.includes(row.status)
  const shown = describe(spec, visual.asset, gamAssets)
  if (running) shown.note = progressOf(row)
  else if (generated && !generated.result && row?.status === 'error')
    shown.note = row.error ?? 'The generation failed'
  const outputs =
    generated?.result && row?.status === 'done' && row.result_ids.length > 1
      ? row.result_ids
      : []
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
      {outputs.length > 0 && (
        <span className="flex gap-1" aria-label="Other outputs">
          {outputs.map((id, n) => (
            <button
              key={id}
              type="button"
              aria-label={`Output ${n + 1}`}
              aria-pressed={generated?.result?.id === id}
              className={`h-8 w-12 overflow-hidden rounded ${
                generated?.result?.id === id ? 'ring-2 ring-primary-600' : ''
              }`}
              onClick={() => row && void choose(row.id, id)}
            >
              {gamAssets[id]?.thumb_url ? (
                <img
                  src={gamAssets[id]?.thumb_url ?? ''}
                  alt=""
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="block h-full w-full bg-gray-200 dark:bg-gray-700" />
              )}
            </button>
          ))}
        </span>
      )}
      {running && row ? (
        <button
          type="button"
          className="btn btn-ghost text-xs"
          onClick={() => void cancel(row.id)}
        >
          <Square className="mr-1 inline h-3 w-3" />
          Stop
        </button>
      ) : (
        generated &&
        !generated.result &&
        onGenerate &&
        (generated.type === 'image' || generated.type === 'video') && (
          <button
            type="button"
            className="btn btn-secondary text-xs"
            onClick={() => onGenerate(visual.asset)}
          >
            <Sparkles className="mr-1 inline h-3 w-3" />
            {row?.status === 'error' ? 'Try again' : 'Generate…'}
          </button>
        )
      )}
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
