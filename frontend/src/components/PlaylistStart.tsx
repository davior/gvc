import { useEffect, useState } from 'react'
import { ListVideo } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '@/api/client'
import { gamApi, type GamPlaylist } from '@/api/gam'
import { useProjectStore } from '@/stores/projects'

/**
 * Start a video from a GAM playlist: pick one, and the project opens laid out as a title
 * card then one scene per item, each moment trimmed as the playlist has it.
 *
 * The playlists are asked for only when this is opened: GAM may be down or predate
 * playlists, and neither should cost the project list anything.
 */
export default function PlaylistStart() {
  const createFromPlaylist = useProjectStore((s) => s.createFromPlaylist)
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [playlists, setPlaylists] = useState<GamPlaylist[] | null>(null)
  const [chosen, setChosen] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || playlists !== null) return
    let stale = false
    gamApi
      .playlists()
      .then((rows) => {
        if (stale) return
        setPlaylists(rows)
        setChosen(rows[0]?.id ?? '')
      })
      .catch((error) => {
        if (!stale) setProblem(apiErrorMessage(error))
      })
    return () => {
      stale = true
    }
  }, [open, playlists])

  async function start() {
    setBusy(true)
    const project = await createFromPlaylist(chosen)
    setBusy(false)
    if (project) navigate(`/p/${project.id}`)
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-secondary" onClick={() => setOpen(true)}>
        <ListVideo className="mr-1 inline h-4 w-4" />
        From a GAM playlist
      </button>
    )
  }

  return (
    <div className="card space-y-3 p-4" aria-label="Start from a playlist" role="group">
      <p className="text-sm text-gray-700 dark:text-gray-300">
        A title card, then each item of the playlist in order: its moments of video with
        their own sound, its pictures held on screen, its sounds over the background.
      </p>
      {problem && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
      {playlists === null && !problem && (
        <p className="text-sm text-gray-500">Loading…</p>
      )}
      {playlists !== null && playlists.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          You have no playlists in GAM yet. Make one there, or ask GAM's assistant for
          one.
        </p>
      )}
      {playlists !== null && playlists.length > 0 && (
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label htmlFor="from-playlist" className="label">
              Playlist
            </label>
            <select
              id="from-playlist"
              className="input w-full"
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
            >
              {playlists.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.item_count} {p.item_count === 1 ? 'item' : 'items'})
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!chosen || busy}
            onClick={() => void start()}
          >
            {busy ? 'Building…' : 'Build video'}
          </button>
        </div>
      )}
      <button
        type="button"
        className="btn btn-ghost text-sm"
        onClick={() => setOpen(false)}
      >
        Cancel
      </button>
    </div>
  )
}
