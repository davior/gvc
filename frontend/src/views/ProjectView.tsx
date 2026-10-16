import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, CloudUpload, Save, Search, Undo2 } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import type { NoteMediaCopy } from '@/api/projects'
import FootageSearch from '@/components/FootageSearch'
import HistoryPanel from '@/components/HistoryPanel'
import RenderPanel from '@/components/RenderPanel'
import SoundtrackPanel from '@/components/SoundtrackPanel'
import IssueList from '@/components/IssueList'
import JsonPanel from '@/components/JsonPanel'
import SceneList from '@/components/SceneList'
import { gamIdsIn, placeHit, resolveSearch, unresolvedSearches } from '@/spec/footage'
import { useProjectStore } from '@/stores/projects'

type Tab = 'scenes' | 'soundtrack' | 'render' | 'json' | 'history'

/** What the footage search is open for: one scene, or a placeholder to resolve. */
type Finding = { kind: 'scene'; index: number } | { kind: 'resolve'; key: string }

const TABS: { id: Tab; label: string }[] = [
  { id: 'scenes', label: 'Scenes' },
  { id: 'soundtrack', label: 'Soundtrack' },
  { id: 'render', label: 'Render' },
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
  const gamAssets = useProjectStore((s) => s.gamAssets)
  const gamError = useProjectStore((s) => s.gamError)
  const loadGamAssets = useProjectStore((s) => s.loadGamAssets)
  const copyNoteMedia = useProjectStore((s) => s.copyNoteMedia)
  const [tab, setTab] = useState<Tab>('scenes')
  const [finding, setFinding] = useState<Finding | null>(null)
  const [copyResult, setCopyResult] = useState<NoteMediaCopy | null>(null)

  useEffect(() => {
    if (id) void open(id)
  }, [id, open])

  // Keyed on the ids as a string, so typing narration does not re-ask GAM; only a
  // newly placed asset does, and the store fetches just the ones it lacks.
  const gamIds = useMemo(() => (draft ? gamIdsIn(draft) : []), [draft])
  const gamKey = gamIds.join(',')
  useEffect(() => {
    if (gamKey) void loadGamAssets(gamKey.split(','))
  }, [gamKey, loadGamAssets])

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
  const toFind = unresolvedSearches(draft)
  const placeholder =
    finding?.kind === 'resolve'
      ? toFind.find((p) => p.key === finding.key)?.ref
      : undefined

  async function onCopy() {
    setCopyResult(await copyNoteMedia())
  }

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
        <div className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          <p>
            {project.pending_note_media} picture or sound file
            {project.pending_note_media === 1 ? ' is' : 's are'} still inside the note
            this came from. Copy {project.pending_note_media === 1 ? 'it' : 'them'} into
            the asset library so this video no longer depends on the note.
          </p>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={dirty || saving}
            title={dirty ? 'Save first: copying writes a new version' : undefined}
            onClick={() => void onCopy()}
          >
            <CloudUpload className="mr-1 inline h-4 w-4" />
            {dirty ? 'Save first, then copy into GAM' : 'Copy into GAM'}
          </button>
        </div>
      )}
      {copyResult && (
        <div role="status" className="text-sm text-gray-700 dark:text-gray-300">
          {copyResult.copied.length > 0 &&
            `Copied ${copyResult.copied.length} into GAM. `}
          {copyResult.failed.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-red-700 dark:text-red-300">
              {copyResult.failed.map((f) => (
                <li key={f.key}>
                  <code className="text-xs">{f.key}</code>: {f.message}
                </li>
              ))}
            </ul>
          )}
        </div>
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

      {tab === 'scenes' && toFind.length > 0 && (
        <section aria-label="To find" className="card space-y-2 p-3">
          <h2 className="text-sm font-medium text-gray-900 dark:text-gray-100">
            Footage still to find
          </h2>
          <ul className="space-y-1">
            {toFind.map(({ key, ref }) => (
              <li key={key} className="flex items-center gap-2 text-sm">
                <span className="flex-1 text-gray-700 dark:text-gray-300">
                  “{ref.query}”
                </span>
                <button
                  type="button"
                  className="btn btn-ghost text-xs"
                  onClick={() => setFinding({ kind: 'resolve', key })}
                >
                  <Search className="mr-1 inline h-3 w-3" />
                  Find
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {tab === 'scenes' && gamError && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Could not show pictures from the asset library: {gamError}
        </p>
      )}
      {tab === 'scenes' && (
        <SceneList
          spec={draft}
          onChange={edit}
          gamAssets={gamAssets}
          onFindFootage={(index) => setFinding({ kind: 'scene', index })}
        />
      )}
      {finding?.kind === 'scene' && (
        <FootageSearch
          title={`Footage for ${draft.segments[finding.index]?.label || 'this scene'}`}
          purpose="scene"
          onClose={() => setFinding(null)}
          onPick={(hit, mode) => {
            edit(placeHit(draft, finding.index, hit, mode))
            setFinding(null)
          }}
        />
      )}
      {finding?.kind === 'resolve' && placeholder && (
        <FootageSearch
          title={`Find: ${placeholder.query}`}
          purpose="resolve"
          initialQuery={placeholder.query}
          initialType={
            placeholder.type === 'image' || placeholder.type === 'audio'
              ? placeholder.type
              : 'video'
          }
          moment={placeholder.moment}
          onClose={() => setFinding(null)}
          onPick={(hit) => {
            edit(resolveSearch(draft, finding.key, hit))
            setFinding(null)
          }}
        />
      )}
      {/* Keyed on the draft, so a change made elsewhere (scene list, revert, save)
          replaces the box's contents instead of leaving a stale copy in it. */}
      {tab === 'json' && (
        <JsonPanel key={JSON.stringify(draft)} spec={draft} onApply={edit} />
      )}
      {tab === 'soundtrack' && (
        <SoundtrackPanel spec={draft} gamAssets={gamAssets} onChange={edit} />
      )}
      {tab === 'render' && (
        <RenderPanel projectId={project.id} dirty={dirty} version={project.version} />
      )}
      {tab === 'history' && <HistoryPanel />}
    </div>
  )
}
