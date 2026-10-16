import { useState } from 'react'
import { apiErrorMessage } from '@/api/client'
import { projectsApi, type SpecIssue, type VideoSpec } from '@/api/projects'
import IssueList from '@/components/IssueList'

interface Props {
  spec: VideoSpec
  onApply: (next: VideoSpec) => void
}

/**
 * The spec as raw JSON: paste one in, or edit anything the scene list does not reach.
 *
 * Edits stay in this box until "Apply", which has the server check them first, so an
 * invalid document never becomes the draft. Remounted (by key) whenever the draft
 * changes elsewhere, so the box never shows a stale copy.
 */
export default function JsonPanel({ spec, onApply }: Props) {
  const [text, setText] = useState(() => JSON.stringify(spec, null, 2))
  const [issues, setIssues] = useState<SpecIssue[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function check(apply: boolean) {
    setIssues([])
    setNote(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (error) {
      setNote(`Not valid JSON: ${error instanceof Error ? error.message : String(error)}`)
      return
    }
    setBusy(true)
    try {
      const result = await projectsApi.validate(parsed)
      if (!result.valid || !result.spec) {
        setIssues(result.issues)
        return
      }
      if (apply) onApply(result.spec)
      else setNote('Valid.')
    } catch (error) {
      setNote(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <textarea
        className="input h-[60vh] w-full font-mono text-xs"
        aria-label="Spec JSON"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={busy}
          onClick={() => void check(false)}
        >
          Check
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => void check(true)}
        >
          Apply to draft
        </button>
        {note && <span className="text-sm text-gray-600 dark:text-gray-400">{note}</span>}
      </div>
      <IssueList issues={issues} />
    </div>
  )
}
