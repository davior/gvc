import { useEffect } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { ACTIVE_TURN } from '@/api/assistant'
import { useAssistantStore } from '@/stores/assistant'

const REFRESH_MS = 20_000

/**
 * In the header: the assistant is working, or has something waiting for you, on some
 * video, with a link to it. Requests run on the server, so this is how one asked and
 * left is found again from anywhere in the app.
 */
export default function AssistantMarker() {
  const attention = useAssistantStore((s) => s.attention)
  const refresh = useAssistantStore((s) => s.refreshAttention)

  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  if (attention.length === 0) return null
  const working = attention.filter((t) => ACTIVE_TURN.includes(t.status))
  const first = working[0] ?? attention[0]
  const to = first.project_id ? `/p/${first.project_id}` : '/projects'
  const label = working.length
    ? `The assistant is working${working.length > 1 ? ` (${working.length})` : ''}`
    : `${attention.length} change${attention.length > 1 ? 's' : ''} to review`

  return (
    <Link
      to={to}
      className="flex items-center gap-1 rounded-full bg-primary-50 px-2 py-1 text-xs text-primary-700 hover:bg-primary-100 dark:bg-primary-900/40 dark:text-primary-200"
      title={first.prompt}
    >
      {working.length ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <Sparkles className="h-3 w-3" />
      )}
      {label}
    </Link>
  )
}
