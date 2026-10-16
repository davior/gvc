import { useEffect } from 'react'
import { useProjectStore } from '@/stores/projects'

/** Every saved version, newest first. A revert is itself a new version. */
export default function HistoryPanel() {
  const versions = useProjectStore((s) => s.versions)
  const project = useProjectStore((s) => s.project)
  const dirty = useProjectStore((s) => s.dirty)
  const saving = useProjectStore((s) => s.saving)
  const loadVersions = useProjectStore((s) => s.loadVersions)
  const revert = useProjectStore((s) => s.revert)

  useEffect(() => {
    void loadVersions()
  }, [loadVersions, project?.id])

  async function onRevert(id: string, seq: number) {
    // Reverting replaces the draft, so unsaved edits would vanish without asking.
    if (
      dirty &&
      !window.confirm(`Discard unsaved changes and go back to version ${seq}?`)
    )
      return
    await revert(id)
  }

  return (
    <ul className="space-y-2">
      {versions.map((version) => (
        <li key={version.id} className="card flex items-center gap-3 p-3 text-sm">
          <span className="w-10 font-mono text-gray-500">v{version.seq}</span>
          <span className="flex-1 text-gray-900 dark:text-gray-100">
            {version.message || 'Saved'}
            {version.author === 'ai' && (
              <span className="ml-2 text-xs text-purple-600">AI</span>
            )}
          </span>
          <span className="text-xs text-gray-500">
            {new Date(version.created_at + 'Z').toLocaleString()}
          </span>
          {version.seq !== project?.version && (
            <button
              type="button"
              className="btn btn-ghost text-xs"
              disabled={saving}
              onClick={() => void onRevert(version.id, version.seq)}
            >
              Revert to this
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
