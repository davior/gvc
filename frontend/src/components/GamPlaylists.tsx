import { useEffect, useState, type FormEvent } from 'react'
import { ArrowLeft, Film, Image as ImageIcon, ListPlus, Search, X } from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import {
  gamApi,
  playlistItemHit,
  type GamHit,
  type GamPlaylist,
  type GamPlaylistDetail,
  type GamPlaylistItem,
  playlistItemFor,
} from '@/api/gam'
import { clock } from '@/spec/footage'

/**
 * GAM's playlists inside Footage Search: find one by name, go through its items in
 * order, take one as footage, or take one out.
 *
 * A playlist is the user's, in GAM, and not part of the video: taking an item out here
 * takes it out of the playlist in GAM, and changes no project.
 */

function itemRange(item: GamPlaylistItem): string {
  if (item.asset_type === 'image') return `${item.image_seconds ?? 5} s`
  if (item.in_point !== null && item.end !== null)
    return `${clock(item.start)}–${clock(item.end)}`
  return item.end !== null ? `all ${clock(item.end)}` : 'all of it'
}

export function PlaylistBrowser({
  selected,
  onSelect,
  refreshKey = 0,
}: {
  selected: GamHit | null
  onSelect: (hit: GamHit) => void
  /** Bumped when something was added elsewhere, so the open playlist is read again. */
  refreshKey?: number
}) {
  const [query, setQuery] = useState('')
  const [list, setList] = useState<GamPlaylist[] | null>(null)
  const [open, setOpen] = useState<GamPlaylistDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)

  async function find(event?: FormEvent) {
    event?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setList(await gamApi.playlists(query))
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function openPlaylist(id: string) {
    setBusy(true)
    setError(null)
    try {
      setOpen(await gamApi.playlist(id))
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(item: GamPlaylistItem) {
    if (!open) return
    setError(null)
    try {
      setOpen(await gamApi.removePlaylistItem(open.id, item.id))
      if (picked === item.id) setPicked(null)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  useEffect(() => {
    // Read once on opening the tab; GAM may be down or predate playlists, which the
    // rest of the dialog should not pay for.
    let stale = false
    gamApi
      .playlists()
      .then((rows) => {
        if (!stale) setList(rows)
      })
      .catch((err) => {
        if (!stale) setError(apiErrorMessage(err))
      })
    return () => {
      stale = true
    }
  }, [])

  const openId = open?.id
  useEffect(() => {
    if (!refreshKey || !openId) return
    let stale = false
    gamApi
      .playlist(openId)
      .then((detail) => {
        if (!stale) setOpen(detail)
      })
      .catch(() => {})
    return () => {
      stale = true
    }
  }, [refreshKey, openId])

  if (open) {
    return (
      <div className="flex min-h-0 flex-col gap-1">
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="btn btn-ghost p-1"
            aria-label="Back to playlists"
            onClick={() => {
              setOpen(null)
              setPicked(null)
            }}
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <p className="flex-1 truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {open.name}
          </p>
          <span className="text-xs text-gray-500">
            {open.items.length} {open.items.length === 1 ? 'item' : 'items'}
          </span>
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <ol className="space-y-1 overflow-auto" aria-label={`Items of ${open.name}`}>
          {open.items.length === 0 && (
            <li className="text-sm text-gray-500">This playlist is empty.</li>
          )}
          {open.items.map((item, n) => (
            <li key={item.id} className="flex items-center gap-1">
              <button
                type="button"
                aria-pressed={picked === item.id && selected !== null}
                disabled={item.missing}
                onClick={() => {
                  setPicked(item.id)
                  onSelect(playlistItemHit(item))
                }}
                className={`flex min-w-0 flex-1 gap-2 rounded p-2 text-left hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-700 ${
                  picked === item.id && selected !== null
                    ? 'bg-primary-50 dark:bg-gray-700'
                    : ''
                }`}
              >
                <span className="w-5 shrink-0 pt-1 text-right text-xs text-gray-400">
                  {n + 1}
                </span>
                {item.thumb_url ? (
                  <img
                    src={item.thumb_url}
                    alt=""
                    className="h-10 w-16 shrink-0 rounded object-cover"
                  />
                ) : (
                  <span className="flex h-10 w-16 shrink-0 items-center justify-center rounded bg-gray-100 dark:bg-gray-800">
                    {item.asset_type === 'image' ? (
                      <ImageIcon className="h-4 w-4 text-gray-400" />
                    ) : (
                      <Film className="h-4 w-4 text-gray-400" />
                    )}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-gray-900 dark:text-gray-100">
                    {item.label || item.asset_name}
                  </span>
                  <span className="block truncate text-xs text-gray-500">
                    {item.label ? `${item.asset_name} · ` : ''}
                    {item.missing ? 'file missing' : itemRange(item)}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className="btn btn-ghost p-1"
                aria-label={`Remove ${item.label || item.asset_name} from the playlist`}
                title="Take out of the playlist (the asset stays in the library)"
                onClick={() => void remove(item)}
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ol>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <form onSubmit={(e) => void find(e)} className="flex gap-1">
        <input
          className="input flex-1 text-sm"
          aria-label="Search playlists"
          placeholder="A playlist's name"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="btn btn-secondary px-2" disabled={busy}>
          <Search className="h-4 w-4" />
          <span className="sr-only">Search playlists</span>
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {list === null && !error && <p className="text-sm text-gray-500">Loading…</p>}
      <ul className="space-y-1 overflow-auto" aria-label="Playlists">
        {list?.length === 0 && (
          <li className="text-sm text-gray-500">
            {query.trim() ? 'No playlist matches.' : 'You have no playlists in GAM yet.'}
          </li>
        )}
        {list?.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              className="flex w-full gap-2 rounded p-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
              onClick={() => void openPlaylist(p.id)}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                  {p.name}
                </span>
                <span className="block truncate text-xs text-gray-500">
                  {p.item_count} {p.item_count === 1 ? 'item' : 'items'}
                  {p.total_seconds > 0 && ` · ${clock(p.total_seconds)}`}
                  {p.description && ` · ${p.description}`}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

const NEW = '__new__'

/**
 * Put what is selected in a GAM playlist: an existing one, or a new one named here. A
 * moment goes in as the stretch the editor would use; anything else as the whole asset.
 */
export function AddToPlaylist({
  hit,
  trim,
  onAdded,
}: {
  hit: GamHit
  trim?: { in: number; out: number }
  onAdded?: (playlist: GamPlaylistDetail) => void
}) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState<GamPlaylist[] | null>(null)
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || list !== null) return
    let stale = false
    gamApi
      .playlists()
      .then((rows) => {
        if (stale) return
        setList(rows)
        setTarget(rows[0]?.id ?? NEW)
      })
      .catch((err) => {
        if (!stale) setError(apiErrorMessage(err))
      })
    return () => {
      stale = true
    }
  }, [open, list])

  // A new selection is a new thing to add: the last one's "Added" no longer applies.
  const hitKey = `${hit.asset.id}:${trim?.in}:${trim?.out}`
  useEffect(() => {
    setMessage(null)
    setError(null)
  }, [hitKey])

  async function add() {
    setBusy(true)
    setError(null)
    setMessage(null)
    const item = playlistItemFor(hit, trim)
    try {
      const result =
        target === NEW
          ? await gamApi.createPlaylist({ name: name.trim(), items: [item] })
          : await gamApi.addPlaylistItems(target, [item])
      setMessage(`Added to ${result.name}.`)
      if (target === NEW) {
        setList((rows) => [result, ...(rows ?? [])])
        setTarget(result.id)
        setName('')
      }
      onAdded?.(result)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="btn btn-ghost px-2 py-1 text-xs"
        onClick={() => setOpen(true)}
      >
        <ListPlus className="mr-1 inline h-3 w-3" />
        Add to a GAM playlist
      </button>
    )
  }

  return (
    <div
      role="group"
      aria-label="Add to a GAM playlist"
      className="space-y-1 rounded border border-gray-200 p-2 dark:border-gray-700"
    >
      <div className="flex flex-wrap items-center gap-1">
        <select
          aria-label="Playlist"
          className="input flex-1 text-xs"
          value={target}
          disabled={list === null}
          onChange={(e) => setTarget(e.target.value)}
        >
          {list?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
          <option value={NEW}>New playlist…</option>
        </select>
        {target === NEW && (
          <input
            className="input flex-1 text-xs"
            aria-label="New playlist's name"
            placeholder="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
        <button
          type="button"
          className="btn btn-secondary px-2 py-1 text-xs"
          disabled={busy || list === null || (target === NEW && !name.trim())}
          onClick={() => void add()}
        >
          Add
        </button>
      </div>
      <p className="text-xs text-gray-500">
        {hit.asset.asset_type !== 'image' && trim
          ? `Adds ${clock(trim.in)}–${clock(trim.out)}.`
          : 'Adds the whole of it.'}
      </p>
      {message && <p className="text-xs text-green-700 dark:text-green-400">{message}</p>}
      {error && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
