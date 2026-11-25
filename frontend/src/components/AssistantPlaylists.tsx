import { useState } from 'react'
import type { PlaylistItemProposal, PlaylistProposal } from '@/api/assistant'
import { clock } from '@/spec/footage'
import { useAssistantStore } from '@/stores/assistant'

/** What one proposed item plays: a stretch, the whole file, or a picture's seconds. */
function plays(item: PlaylistItemProposal): string {
  if (item.type === 'image') return `picture, ${item.image_seconds ?? 5} s`
  if (item.in_point !== null && item.out_point !== null)
    return `${clock(item.in_point)}–${clock(item.out_point)}`
  return 'all of it'
}

/**
 * A change to one of the user's GAM playlists, or a new one. Apart from the video's
 * proposal: it never touches the editor, and GAM changes only when the person presses
 * the button, as them.
 */
export default function PlaylistProposalCard({
  turnId,
  proposal,
}: {
  turnId: string
  proposal: PlaylistProposal
}) {
  const decidePlaylist = useAssistantStore((s) => s.decidePlaylist)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  // A new playlist has no id until it is made; once made, it reads as any other.
  const isNew = proposal.playlist_id === null

  async function decide(apply: boolean) {
    setBusy(true)
    await decidePlaylist(turnId, proposal.playlist_ref, apply)
    setBusy(false)
  }

  const counts = [
    proposal.add.length && `add ${proposal.add.length}`,
    proposal.remove.length && `remove ${proposal.remove.length}`,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div
      aria-label={`Playlist: ${proposal.name}`}
      className="space-y-2 rounded border border-gray-200 p-2 text-xs dark:border-gray-700"
    >
      <p className="font-medium text-gray-900 dark:text-gray-100">
        {isNew ? 'New GAM playlist' : 'GAM playlist'}: {proposal.name}
      </p>
      <p className="text-gray-600 dark:text-gray-400">
        {counts} {proposal.add.length + proposal.remove.length === 1 ? 'item' : 'items'}.{' '}
        <button
          type="button"
          className="text-blue-700 hover:underline dark:text-blue-300"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? 'Hide the items' : 'Show the items'}
        </button>
      </p>
      {open && (
        <ul
          aria-label={`Changes to ${proposal.name}`}
          className="max-h-72 space-y-0.5 overflow-auto rounded bg-gray-50 p-2 dark:bg-gray-900"
        >
          {proposal.add.map((item, i) => (
            <li key={`a${i}`} className="text-gray-700 dark:text-gray-300">
              <span className="text-green-700 dark:text-green-400">+ </span>
              {item.label ? `${item.label} (${item.name})` : item.name} · {plays(item)}
            </li>
          ))}
          {proposal.remove.map((item) => (
            <li key={item.item_id} className="text-gray-700 dark:text-gray-300">
              <span className="text-red-700 dark:text-red-400">− </span>
              {item.label ? `${item.label} (${item.name})` : item.name}
            </li>
          ))}
        </ul>
      )}
      {proposal.state === 'pending' && (
        <div className="flex gap-2">
          <button
            type="button"
            className="btn btn-primary px-2 py-1 text-xs"
            disabled={busy}
            onClick={() => void decide(true)}
          >
            {isNew ? 'Create in GAM' : 'Change in GAM'}
          </button>
          <button
            type="button"
            className="btn btn-secondary px-2 py-1 text-xs"
            disabled={busy}
            onClick={() => void decide(false)}
          >
            Discard
          </button>
        </div>
      )}
      {proposal.state === 'applied' && (
        <div className="space-y-0.5 text-gray-600 dark:text-gray-400">
          <p>
            Done.{' '}
            {proposal.playlist_url && (
              <a
                href={proposal.playlist_url}
                target="_blank"
                rel="noreferrer"
                className="text-blue-700 hover:underline dark:text-blue-300"
              >
                Open in GAM
              </a>
            )}
          </p>
          {proposal.skipped.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
      {proposal.state === 'discarded' && <p className="text-gray-500">Discarded.</p>}
    </div>
  )
}
