import { useEffect, useState, type FormEvent } from 'react'
import { Film, FileText, Plus, Sparkles, Trash2 } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import type { Origin } from '@/api/projects'
import { useProjectStore } from '@/stores/projects'

const ORIGIN_LABEL: Record<Origin, string> = {
  blank: 'Made by hand',
  pasted: 'From a pasted spec',
  note: 'Pushed from Notes',
  brief: 'Drafted from a prompt',
}

function OriginIcon({ origin }: { origin: Origin }) {
  if (origin === 'note') return <FileText className="h-4 w-4" />
  if (origin === 'brief') return <Sparkles className="h-4 w-4" />
  return <Film className="h-4 w-4" />
}

/** Every project, newest change first, and the way to start a new one by hand. */
export default function ProjectListView() {
  const list = useProjectStore((s) => s.list)
  const loading = useProjectStore((s) => s.listLoading)
  const error = useProjectStore((s) => s.listError)
  const loadList = useProjectStore((s) => s.loadList)
  const createBlank = useProjectStore((s) => s.createBlank)
  const remove = useProjectStore((s) => s.remove)
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    void loadList()
  }, [loadList])

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    setCreating(true)
    const project = await createBlank(title)
    setCreating(false)
    if (project) navigate(`/p/${project.id}`)
  }

  async function onDelete(id: string, name: string) {
    if (!window.confirm(`Delete "${name}" and its whole history?`)) return
    await remove(id)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <form onSubmit={onCreate} className="card flex items-end gap-3 p-4">
        <div className="flex-1">
          <label htmlFor="new-title" className="label">
            New video
          </label>
          <input
            id="new-title"
            className="input w-full"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary" disabled={creating}>
          <Plus className="mr-1 inline h-4 w-4" />
          New blank video
        </button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {loading && list.length === 0 ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : list.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No videos yet. Start one above, or push a note from Gecko Notes.
        </p>
      ) : (
        <ul className="space-y-2">
          {list.map((project) => (
            <li key={project.id} className="card flex items-center gap-3 p-3">
              <span className="text-gray-400" title={ORIGIN_LABEL[project.origin]}>
                <OriginIcon origin={project.origin} />
              </span>
              <Link
                to={`/p/${project.id}`}
                className="flex-1 font-medium text-gray-900 hover:underline dark:text-gray-100"
              >
                {project.title}
              </Link>
              <span className="text-xs text-gray-500">
                {ORIGIN_LABEL[project.origin]} · v{project.version}
              </span>
              <button
                type="button"
                className="btn btn-ghost p-2"
                aria-label={`Delete ${project.title}`}
                onClick={() => void onDelete(project.id, project.title)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
