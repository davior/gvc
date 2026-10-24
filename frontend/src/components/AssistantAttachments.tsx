import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  FileText,
  Globe,
  ImageIcon,
  Loader2,
  Paperclip,
  StickyNote,
  X,
} from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import {
  assistantApi,
  type Attachment,
  type AttachmentKind,
  type NoteChoice,
} from '@/api/assistant'
import { useAssistantStore } from '@/stores/assistant'

/**
 * What the assistant has been given to work from: files, pictures, notes from Gecko
 * Notes and web pages. Each is read once, when attached, and every request in the
 * conversation reads it from then on; removing one takes it out of the next request.
 *
 * What the server can read is a text, Markdown, subtitle, CSV, PDF, Word or HTML file,
 * or a JPEG, PNG, WebP or GIF picture; `ACCEPT` mirrors it so the file dialog offers
 * those first. Pictures are refused, with a reason, when the AI model in Settings isn't
 * marked as one that can look at images.
 */

const ACCEPT =
  '.txt,.md,.markdown,.csv,.tsv,.json,.srt,.vtt,.log,.yaml,.yml,.xml,.rst,.org,.pdf,.docx,.html,.htm,text/*,application/pdf,.jpg,.jpeg,.png,.webp,.gif,image/jpeg,image/png,image/webp,image/gif'

const KIND_ICON: Record<AttachmentKind, ReactNode> = {
  file: <FileText className="h-3 w-3 shrink-0" />,
  note: <StickyNote className="h-3 w-3 shrink-0" />,
  url: <Globe className="h-3 w-3 shrink-0" />,
  image: <ImageIcon className="h-3 w-3 shrink-0" />,
}

// One empty list, not a new one per read: a selector returning a fresh array makes
// the store look changed on every render, and React loops.
const NONE: Attachment[] = []

function size(a: Attachment): string {
  if (a.kind === 'image')
    return a.width && a.height ? `${a.width}×${a.height}` : 'picture'
  return a.chars >= 1000
    ? `${Math.round(a.chars / 1000)}k characters`
    : `${a.chars} characters`
}

/** The conversation's attachments, each removable. */
export function AttachmentList() {
  const attachments = useAssistantStore((s) => s.chat?.attachments ?? NONE)
  const detach = useAssistantStore((s) => s.detach)
  if (attachments.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Attached">
      {attachments.map((a) => (
        <li
          key={a.id}
          className="flex max-w-full items-center gap-1 rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
          title={`${a.source}\n${size(a)}${a.truncated ? ', only the beginning was kept' : ''}\n\n${a.preview}`}
        >
          {a.thumb ? (
            <img src={a.thumb} alt="" className="h-5 w-5 shrink-0 rounded object-cover" />
          ) : (
            KIND_ICON[a.kind]
          )}
          <span className="min-w-0 truncate">{a.title}</span>
          {a.truncated && <span className="shrink-0 text-amber-600">(cut short)</span>}
          <button
            type="button"
            className="shrink-0 rounded p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700"
            aria-label={`Remove ${a.title}`}
            onClick={() => void detach(a.id)}
          >
            <X className="h-3 w-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}

function UrlForm({ onDone }: { onDone: () => void }) {
  const attach = useAssistantStore((s) => s.attach)
  const attaching = useAssistantStore((s) => s.attaching)
  const [url, setUrl] = useState('')

  async function submit() {
    if (!url.trim() || attaching) return
    if (await attach({ url: url.trim() })) onDone()
  }

  return (
    <form
      className="flex gap-1"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      <input
        autoFocus
        className="input min-w-0 flex-1 py-1 text-xs"
        aria-label="Web page address"
        placeholder="https://…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onDone()}
      />
      <button
        type="submit"
        className="btn btn-primary px-2 py-1 text-xs"
        disabled={!url.trim() || attaching}
      >
        Attach
      </button>
    </form>
  )
}

/** Notes in Gecko Notes, searched as you type, to attach one. */
function NotePicker({ onDone }: { onDone: () => void }) {
  const attach = useAssistantStore((s) => s.attach)
  const attaching = useAssistantStore((s) => s.attaching)
  const [query, setQuery] = useState('')
  const [notes, setNotes] = useState<NoteChoice[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  useEffect(() => {
    // Every keystroke starts a search, and only the last one's answer is shown.
    const mine = ++latest.current
    const timer = setTimeout(
      () => {
        assistantApi.findNotes(query.trim()).then(
          (found) => {
            if (mine !== latest.current) return
            setNotes(found)
            setError(null)
          },
          (e) => {
            if (mine === latest.current) setError(apiErrorMessage(e))
          }
        )
      },
      query ? 250 : 0
    )
    return () => clearTimeout(timer)
  }, [query])

  return (
    <div className="space-y-1">
      <input
        autoFocus
        className="input w-full py-1 text-xs"
        aria-label="Search your notes"
        placeholder="Search your notes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onDone()}
      />
      {error && <p className="text-[11px] text-red-600 dark:text-red-400">{error}</p>}
      {notes && notes.length === 0 && !error && (
        <p className="text-[11px] text-gray-500">No notes found.</p>
      )}
      {notes && notes.length > 0 && (
        <ul
          className="max-h-48 overflow-auto rounded border border-gray-200 dark:border-gray-700"
          aria-label="Notes"
        >
          {notes.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className="block w-full px-2 py-1 text-left text-xs hover:bg-gray-50 disabled:opacity-50 dark:hover:bg-gray-700"
                disabled={attaching}
                onClick={async () => {
                  if (await attach({ noteId: n.id })) onDone()
                }}
              >
                <span className="block truncate font-medium">{n.title}</span>
                {n.preview && (
                  <span className="block truncate text-[11px] text-gray-500">
                    {n.preview}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

type Mode = 'menu' | 'note' | 'url' | null

/** The paperclip: attach a file, a note or a web page. */
export function AttachControls() {
  const attach = useAssistantStore((s) => s.attach)
  const attaching = useAssistantStore((s) => s.attaching)
  const [mode, setMode] = useState<Mode>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function pickFiles(files: FileList | null) {
    setMode(null)
    for (const file of Array.from(files ?? [])) {
      // One at a time, so a refusal names the file it was about.
      if (!(await attach({ file }))) break
    }
    if (fileInput.current) fileInput.current.value = ''
  }

  const item =
    'flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700'

  return (
    <div className="relative">
      <input
        ref={fileInput}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        aria-label="Attach files"
        onChange={(e) => void pickFiles(e.target.files)}
      />
      <button
        type="button"
        className="btn btn-ghost p-2"
        aria-label="Attach"
        title="Attach a file, a note or a web page for the assistant to work from"
        aria-expanded={mode !== null}
        disabled={attaching}
        onClick={() => setMode(mode ? null : 'menu')}
      >
        {attaching ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Paperclip className="h-4 w-4" />
        )}
      </button>
      {mode && (
        <div className="absolute bottom-full left-0 z-10 mb-1 w-72 rounded border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-700 dark:bg-gray-800">
          {mode === 'menu' && (
            <div role="menu">
              <button
                type="button"
                role="menuitem"
                className={item}
                onClick={() => fileInput.current?.click()}
              >
                <FileText className="h-3.5 w-3.5" /> A file or picture (text, PDF, Word,
                images…)
              </button>
              <button
                type="button"
                role="menuitem"
                className={item}
                onClick={() => setMode('note')}
              >
                <StickyNote className="h-3.5 w-3.5" /> A note from Gecko Notes
              </button>
              <button
                type="button"
                role="menuitem"
                className={item}
                onClick={() => setMode('url')}
              >
                <Globe className="h-3.5 w-3.5" /> A web page
              </button>
            </div>
          )}
          {mode === 'note' && <NotePicker onDone={() => setMode(null)} />}
          {mode === 'url' && <UrlForm onDone={() => setMode(null)} />}
        </div>
      )}
    </div>
  )
}
