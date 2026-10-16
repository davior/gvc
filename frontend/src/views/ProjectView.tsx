import { useEffect, useState } from 'react'
import { ArrowLeft, Save, Undo2 } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import HistoryPanel from '@/components/HistoryPanel'
import IssueList from '@/components/IssueList'
import JsonPanel from '@/components/JsonPanel'
import SceneList from '@/components/SceneList'
import { useProjectStore } from '@/stores/projects'

type Tab = 'scenes' | 'json' | 'history'

const TABS: { id: Tab; label: string }[] = [
  { id: 'scenes', label: 'Scenes' },
  { id: 'json', label: 'JSON' },
  { id: 'history', label: 'History' },
]

/** One project: its scenes, its raw spec and its history, over one shared draft. */
export default function ProjectView() {
  const { id } = useParams<{ id: string }>()
  const open = useProjectStore((s) => s.open)
  const project = useProjectStore((s) => s.project)
  const draft = useProjectStore((s) => s.draft)
  const dirty = useProjectStore((s) => s.dirty)
  const loading = useProjectStore((s) => s.loading)
  const saving = useProjectStore((s) => s.saving)
  const error = useProjectStore((s) => s.error)
  const issues = useProjectStore((s) => s.issues)
  const edit = useProjectStore((s) => s.edit)
  const save = useProjectStore((s) => s.save)
  const discard = useProjectStore((s) => s.discard)
  const [tab, setTab] = useState<Tab>('scenes')

  useEffect(() => {
    if (id) void open(id)
  }, [id, open])

  if (loading || (!project && !error)) {
    return <p className="p-6 text-sm text-gray-500">Loading…</p>
  }
  if (!project || !draft) {
    return (
      <div className="space-y-2 p-6">
        <p role="alert" className="text-sm text-red-600">
          {error ?? 'Project not found'}
        </p>
        <Link to="/projects" className="text-sm underline">
          Back to all videos
        </Link>
      </div>
    )
  }

  const source = draft.source
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Link to="/projects" className="btn btn-ghost p-2" aria-label="All videos">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <input
          className="input flex-1 text-lg font-semibold"
          aria-label="Video title"
          value={draft.title}
          onChange={(e) => edit({ ...draft, title: e.target.value })}
        />
        {dirty && (
          <button type="button" className="btn btn-ghost" onClick={discard}>
            <Undo2 className="mr-1 inline h-4 w-4" />
            Discard
          </button>
        )}
        <button
          type="button"
          className="btn btn-primary"
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          <Save className="mr-1 inline h-4 w-4" />
          {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
        </button>
      </div>

      <p className="text-xs text-gray-500">
        Version {project.version}
        {source?.kind === 'note' &&
          ' · pushed from Gecko Notes; edited only here from now on'}
        {source?.kind === 'brief' && ' · drafted from a prompt'}
      </p>

      {project.pending_note_media > 0 && (
        <p className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          {project.pending_note_media} picture or sound file
          {project.pending_note_media === 1 ? ' is' : 's are'} still inside the note this
          came from. They move into the asset library once GVC is connected to it.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      <IssueList issues={issues} />

      <div
        role="tablist"
        className="flex gap-1 border-b border-gray-200 dark:border-gray-700"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm ${
              tab === t.id
                ? 'border-b-2 border-primary-600 font-medium text-gray-900 dark:text-gray-100'
                : 'text-gray-500'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'scenes' && <SceneList spec={draft} onChange={edit} />}
      {/* Keyed on the draft, so a change made elsewhere (scene list, revert, save)
          replaces the box's contents instead of leaving a stale copy in it. */}
      {tab === 'json' && (
        <JsonPanel key={JSON.stringify(draft)} spec={draft} onApply={edit} />
      )}
      {tab === 'history' && <HistoryPanel />}
    </div>
  )
}
