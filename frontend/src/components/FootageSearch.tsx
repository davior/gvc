import { useState, type FormEvent, type ReactNode } from 'react'
import { Film, Image as ImageIcon, Search, X } from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import { gamApi, type GamHit, type GamSearch, type MediaKind } from '@/api/gam'
import { clock, momentTrim, type MomentSize, type PlaceMode } from '@/spec/footage'

/**
 * - `scene`: footage for one scene, as b-roll under its narration or as a clip with
 *   its own sound.
 * - `resolve`: whatever answers a `search` placeholder.
 * - `track`: a sound to play under the video: music, an effect, a voice.
 */
type Purpose = 'scene' | 'resolve' | 'track'

interface Props {
  title: string
  purpose: Purpose
  initialQuery?: string
  initialType?: MediaKind
  /** How long a found moment should be: a placeholder's `moment`, or the default. */
  moment?: MomentSize
  onPick: (hit: GamHit, mode: PlaceMode) => void
  onClose: () => void
}

const TYPES: { id: MediaKind | undefined; label: string }[] = [
  { id: 'video', label: 'Video' },
  { id: 'image', label: 'Pictures' },
  { id: 'audio', label: 'Sound' },
  { id: undefined, label: 'Everything' },
]

/** GAM's «matched» words, shown marked rather than with the guillemets. */
function Snippet({ text }: { text: string }) {
  const parts: ReactNode[] = []
  text.split(/«([^»]*)»/).forEach((part, i) => {
    if (part) parts.push(i % 2 === 1 ? <mark key={i}>{part}</mark> : part)
  })
  return <p className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">{parts}</p>
}

/**
 * Searching GAM for something to show, including "where people talk about X": GAM
 * searches what is said in its videos, and a hit on a line comes back as the moment
 * it was said, which becomes the trim.
 */
export default function FootageSearch({
  title,
  purpose,
  initialQuery = '',
  initialType = 'video',
  moment,
  onPick,
  onClose,
}: Props) {
  const [query, setQuery] = useState(initialQuery)
  const [type, setType] = useState<MediaKind | undefined>(initialType)
  const [result, setResult] = useState<GamSearch | null>(null)
  const [selected, setSelected] = useState<GamHit | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(event?: FormEvent) {
    event?.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    setError(null)
    setSelected(null)
    try {
      setResult(await gamApi.search(query, type))
    } catch (err) {
      setResult(null)
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const trim = selected ? momentTrim(selected, moment) : undefined
  const isVideo = selected?.asset.asset_type === 'video'

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-black/40 p-4 pt-12"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={title}
        className="card flex max-h-[85vh] w-full max-w-3xl flex-col gap-3 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <h2 className="flex-1 font-semibold text-gray-900 dark:text-gray-100">
            {title}
          </h2>
          <button
            type="button"
            className="btn btn-ghost p-2"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={(e) => void run(e)} className="flex gap-2">
          <input
            className="input flex-1"
            aria-label="Search the asset library"
            placeholder="What is said, or what it shows: e.g. people talking about water"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Search className="mr-1 inline h-4 w-4" />
            Search
          </button>
        </form>

        <div className="flex gap-1" role="group" aria-label="Kind of media">
          {TYPES.map((t) => (
            <button
              key={t.label}
              type="button"
              aria-pressed={type === t.id}
              className={`btn text-xs ${type === t.id ? 'btn-secondary' : 'btn-ghost'}`}
              onClick={() => setType(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        {result && !result.semantic && (
          <p className="text-xs text-gray-500">
            {result.semantic_error
              ? `Matched on words only: GAM's meaning-based search failed (${result.semantic_error}).`
              : "Matched on words only: meaning-based search isn't set up in GAM."}
          </p>
        )}

        <div className="grid min-h-0 flex-1 gap-3 overflow-hidden md:grid-cols-2">
          <ul className="space-y-1 overflow-auto" aria-label="Results">
            {result?.data.length === 0 && (
              <li className="text-sm text-gray-500">Nothing in the library matches.</li>
            )}
            {result?.data.map((h, i) => (
              <li key={`${h.asset.id}-${i}`}>
                <button
                  type="button"
                  aria-pressed={selected === h}
                  onClick={() => setSelected(h)}
                  className={`flex w-full gap-2 rounded p-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 ${
                    selected === h ? 'bg-primary-50 dark:bg-gray-700' : ''
                  }`}
                >
                  {h.asset.thumb_url ? (
                    <img
                      src={h.asset.thumb_url}
                      alt=""
                      className="h-12 w-20 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <span className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-gray-100 dark:bg-gray-800">
                      {h.asset.asset_type === 'image' ? (
                        <ImageIcon className="h-4 w-4 text-gray-400" />
                      ) : (
                        <Film className="h-4 w-4 text-gray-400" />
                      )}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                      {h.asset.name}
                    </span>
                    {h.start_time !== null && (
                      <span className="text-xs text-gray-500">
                        at {clock(h.start_time)}
                        {h.end_time !== null && `–${clock(h.end_time)}`}
                      </span>
                    )}
                    {h.snippet && <Snippet text={h.snippet} />}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {selected && (
            <div className="space-y-2" aria-label="Selected">
              {isVideo && selected.asset.file_url ? (
                <video
                  key={`${selected.asset.id}-${trim?.in}`}
                  controls
                  preload="metadata"
                  className="w-full rounded bg-black"
                  src={
                    trim
                      ? `${selected.asset.file_url}#t=${trim.in},${trim.out}`
                      : selected.asset.file_url
                  }
                />
              ) : selected.asset.asset_type === 'audio' && selected.asset.file_url ? (
                <audio
                  key={selected.asset.id}
                  controls
                  preload="metadata"
                  className="w-full"
                  src={selected.asset.file_url}
                />
              ) : selected.asset.file_url ? (
                <img
                  src={selected.asset.file_url}
                  alt={selected.asset.name}
                  className="w-full rounded"
                />
              ) : null}
              <p className="text-sm text-gray-700 dark:text-gray-300">
                {purpose === 'track'
                  ? selected.asset.duration_seconds
                    ? `${clock(selected.asset.duration_seconds)} long`
                    : 'A sound'
                  : trim
                    ? `Uses ${clock(trim.in)}–${clock(trim.out)} (${Math.round(trim.out - trim.in)} s)`
                    : isVideo
                      ? 'Uses the whole video'
                      : 'A still picture'}
              </p>
              {selected.asset.credit && (
                <p className="text-xs text-gray-500">{selected.asset.credit}</p>
              )}
              <div className="flex flex-wrap gap-2">
                {purpose === 'track' ? (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => onPick(selected, 'broll')}
                  >
                    Use this track
                  </button>
                ) : purpose === 'resolve' ? (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => onPick(selected, 'broll')}
                  >
                    Use this
                  </button>
                ) : isVideo ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={() => onPick(selected, 'broll')}
                    >
                      Use as b-roll
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => onPick(selected, 'clip')}
                    >
                      Play with its sound
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => onPick(selected, 'broll')}
                  >
                    Use this picture
                  </button>
                )}
              </div>
              {purpose === 'scene' && isVideo && (
                <p className="text-xs text-gray-500">
                  B-roll plays silently under this scene&apos;s narration. With its sound,
                  the scene becomes a clip and its narration is set aside (Discard brings
                  it back).
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
