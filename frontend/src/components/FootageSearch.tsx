import { createPortal } from 'react-dom'
import { useState, type FormEvent, type ReactNode } from 'react'
import {
  Film,
  Globe,
  Image as ImageIcon,
  Library,
  ListVideo,
  Search,
  X,
} from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import { webApi, type WebImage } from '@/api/web'
import {
  gamApi,
  audioSummary,
  type GamHit,
  type GamSearch,
  type MediaKind,
} from '@/api/gam'
import { clock, momentTrim, type MomentSize, type PlaceMode } from '@/spec/footage'
import WaveformPlayer from '@/components/WaveformPlayer'
import WebPictures from '@/components/WebPictures'
import { AddToPlaylist, PlaylistBrowser } from '@/components/GamPlaylists'

/**
 * - `scene`: footage for one scene, as b-roll under its narration or as a clip with
 *   its own sound.
 * - `resolve`: whatever answers a `search` placeholder.
 * - `track`: a sound to play under the video: music, an effect, a voice.
 * - `overlay`: a picture shown over a scene (a logo, a map, an inset).
 * - `picture`: a picture for the project itself (its watermark, its background).
 */
type Purpose = 'scene' | 'resolve' | 'track' | 'overlay' | 'picture'

interface Props {
  title: string
  purpose: Purpose
  initialQuery?: string
  initialType?: MediaKind
  /** How long a found moment should be: a placeholder's `moment`, or the default. */
  moment?: MomentSize
  onPick: (hit: GamHit, mode: PlaceMode) => void
  onClose: () => void
  /** Pictures from the web already found for this (a placeholder's shortlist): the
   *  dialog opens on them. */
  candidates?: WebImage[]
  /** The project the search is for, so the suite can say what it cost. */
  projectId?: string
}

type Source = 'library' | 'web' | 'playlists'

/** What choosing a web picture is called, in the words the library's results use. */
const WEB_USE_LABEL: Record<Purpose, string> = {
  scene: 'Use this picture',
  resolve: 'Use this',
  track: '',
  overlay: 'Put on screen',
  picture: 'Use this picture',
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
  candidates,
  projectId,
}: Props) {
  // The web has pictures only, so a sound has nothing to find there.
  const webOffered = purpose !== 'track'
  const [source, setSource] = useState<Source>(
    webOffered && candidates?.length ? 'web' : 'library'
  )
  const [web, setWeb] = useState<WebImage[] | null>(
    candidates?.length ? candidates : null
  )
  const [query, setQuery] = useState(initialQuery)
  const [type, setType] = useState<MediaKind | undefined>(initialType)
  const [result, setResult] = useState<GamSearch | null>(null)
  const [selected, setSelected] = useState<GamHit | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Bumped when the selection was added to a playlist, so an open one shows it.
  const [playlistsChanged, setPlaylistsChanged] = useState(0)

  async function run(event?: FormEvent, from: Source = source) {
    event?.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    setError(null)
    setSelected(null)
    try {
      if (from === 'web') setWeb(await webApi.images(query, projectId))
      else setResult(await gamApi.search(query, type))
    } catch (err) {
      if (from === 'web') setWeb(null)
      else setResult(null)
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function switchTo(next: Source) {
    setSource(next)
    setError(null)
    setSelected(null)
    // A playlist is found by its name, in its own box, not by the footage words.
    if (next === 'playlists') return
    // Searching the other place for the same words is what switching is for.
    if (next === 'web' ? web === null : result === null) void run(undefined, next)
  }

  const trim = selected ? momentTrim(selected, moment) : undefined
  const isVideo = selected?.asset.asset_type === 'video'
  // What the waveform shows as the stretch that matters: the line that matched, or
  // else a GAM clip's own bounds (its file is the parent's, so they line up). Display
  // only — a track is still used whole.
  const audioMoment =
    trim ??
    (selected && selected.asset.in_point !== null && selected.asset.out_point !== null
      ? { in: selected.asset.in_point, out: selected.asset.out_point }
      : undefined)

  // Portalled to <body>: a glass theme blurs the settings panels, and a blurred element
  // both traps `position: fixed` descendants and makes its own stacking layer, so an
  // inline dialog was sized to its panel and painted under the panels after it.
  return createPortal(
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

        {source !== 'playlists' && (
          <form onSubmit={(e) => void run(e)} className="flex gap-2">
            <input
              className="input flex-1"
              aria-label={
                source === 'web'
                  ? 'Search the web for pictures'
                  : 'Search the asset library'
              }
              placeholder={
                source === 'web'
                  ? 'What the picture shows: e.g. a dry riverbed at noon'
                  : 'What is said, or what it shows: e.g. people talking about water'
              }
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
            <button type="submit" className="btn btn-primary" disabled={busy}>
              <Search className="mr-1 inline h-4 w-4" />
              Search
            </button>
          </form>
        )}

        <div className="flex gap-1" role="group" aria-label="Where to look">
          <button
            type="button"
            aria-pressed={source === 'library'}
            className={`btn text-xs ${source === 'library' ? 'btn-secondary' : 'btn-ghost'}`}
            onClick={() => switchTo('library')}
          >
            <Library className="mr-1 inline h-3 w-3" />
            Library
          </button>
          {webOffered && (
            <button
              type="button"
              aria-pressed={source === 'web'}
              className={`btn text-xs ${source === 'web' ? 'btn-secondary' : 'btn-ghost'}`}
              onClick={() => switchTo('web')}
            >
              <Globe className="mr-1 inline h-3 w-3" />
              Web pictures
            </button>
          )}
          <button
            type="button"
            aria-pressed={source === 'playlists'}
            className={`btn text-xs ${source === 'playlists' ? 'btn-secondary' : 'btn-ghost'}`}
            onClick={() => switchTo('playlists')}
          >
            <ListVideo className="mr-1 inline h-3 w-3" />
            Playlists
          </button>
        </div>

        {source === 'library' && (
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
        )}

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        {source === 'library' && result && !result.semantic && (
          <p className="text-xs text-gray-500">
            {result.semantic_error
              ? `Matched on words only: GAM's meaning-based search failed (${result.semantic_error}).`
              : "Matched on words only: meaning-based search isn't set up in GAM."}
          </p>
        )}

        {source === 'web' ? (
          web && (
            <WebPictures
              images={web}
              useLabel={WEB_USE_LABEL[purpose]}
              onPick={(hit) => onPick(hit, 'broll')}
            />
          )
        ) : (
          <div className="grid min-h-0 flex-1 gap-3 overflow-hidden md:grid-cols-2">
            {source === 'playlists' ? (
              <PlaylistBrowser
                selected={selected}
                onSelect={setSelected}
                refreshKey={playlistsChanged}
              />
            ) : (
              <ul className="space-y-1 overflow-auto" aria-label="Results">
                {result?.data.length === 0 && (
                  <li className="text-sm text-gray-500">
                    Nothing in the library matches.
                  </li>
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
                        {audioSummary(h.asset) && (
                          <span className="block truncate text-xs text-gray-500">
                            {audioSummary(h.asset)}
                          </span>
                        )}
                        {h.snippet && <Snippet text={h.snippet} />}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

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
                  <WaveformPlayer
                    key={`${selected.asset.id}-${audioMoment?.in}`}
                    assetId={selected.asset.id}
                    src={selected.asset.file_url}
                    name={selected.asset.name}
                    moment={audioMoment}
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
                    ? [
                        selected.asset.duration_seconds
                          ? `${clock(selected.asset.duration_seconds)} long`
                          : 'A sound',
                        audioMoment &&
                          `${trim ? 'matched at' : 'clip of'} ${clock(audioMoment.in)}–${clock(audioMoment.out)}`,
                      ]
                        .filter(Boolean)
                        .join(' · ')
                    : trim
                      ? `Uses ${clock(trim.in)}–${clock(trim.out)} (${Math.round(trim.out - trim.in)} s)`
                      : isVideo
                        ? 'Uses the whole video'
                        : 'A still picture'}
                </p>
                {audioSummary(selected.asset) && (
                  <p className="text-xs text-gray-600 dark:text-gray-400">
                    {audioSummary(selected.asset)}
                  </p>
                )}
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
                  ) : purpose === 'overlay' || purpose === 'picture' ? (
                    selected.asset.asset_type === 'image' ? (
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => onPick(selected, 'broll')}
                      >
                        {purpose === 'picture' ? 'Use this picture' : 'Put on screen'}
                      </button>
                    ) : (
                      <p className="text-xs text-gray-500">
                        Only a picture can be used here.
                      </p>
                    )
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
                <AddToPlaylist
                  hit={selected}
                  trim={trim}
                  onAdded={() => setPlaylistsChanged((n) => n + 1)}
                />
                {purpose === 'scene' && isVideo && (
                  <p className="text-xs text-gray-500">
                    B-roll plays silently under this scene&apos;s narration. With its
                    sound, the scene becomes a clip and its narration is set aside
                    (Discard brings it back).
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
