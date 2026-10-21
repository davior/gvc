import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Check,
  ChevronDown,
  ChevronRight,
  History,
  Loader2,
  MessageSquarePlus,
  PanelRightClose,
  PanelRightOpen,
  Search,
  Send,
  Sparkles,
  Square,
  Trash2,
  TriangleAlert,
  Wrench,
} from 'lucide-react'
import { Link, useMatch, useNavigate } from 'react-router-dom'
import { ACTIVE_TURN, type Turn, type TurnStep } from '@/api/assistant'
import { formatCost } from '@/api/usage'
import { AttachControls, AttachmentList } from '@/components/AssistantAttachments'
import { MAX_WIDTH, MIN_WIDTH, useAssistantStore } from '@/stores/assistant'
import { useGenerationStore } from '@/stores/generations'
import { useProjectStore } from '@/stores/projects'

/**
 * The assistant, always to hand at the side of every page, as in Gecko Notes.
 *
 * On a project it talks about that project, starting from the editor's draft with any
 * unsaved edits; on the project list, about a new video. What it changes comes back as
 * a proposal to apply or discard, so it can never alter a video behind your back. A
 * request keeps running on the server with this page closed, and is found here again
 * on the way back, still running or still waiting.
 */

/** Paragraphs, lists, **bold**, _italic_ and `code`: what a reply uses, no more. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
      return (
        <code key={i} className="rounded bg-gray-100 px-1 text-[0.85em] dark:bg-gray-700">
          {part.slice(1, -1)}
        </code>
      )
    if (part.startsWith('_') && part.endsWith('_') && part.length > 2)
      return <em key={i}>{part.slice(1, -1)}</em>
    return <Fragment key={i}>{part}</Fragment>
  })
}

function Prose({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  return (
    <div className="space-y-2">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        if (lines.every((l) => /^\s*[-*] /.test(l)))
          return (
            <ul key={i} className="list-disc space-y-0.5 pl-4">
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*[-*] /, ''))}</li>
              ))}
            </ul>
          )
        return (
          <p key={i} className="whitespace-pre-wrap">
            {inline(block)}
          </p>
        )
      })}
    </div>
  )
}

const STEP_ICON: Record<TurnStep['kind'], ReactNode> = {
  search: <Search className="h-3 w-3" />,
  edit: <Wrench className="h-3 w-3" />,
  issue: <TriangleAlert className="h-3 w-3 text-amber-600" />,
  think: <Sparkles className="h-3 w-3" />,
  note: <Sparkles className="h-3 w-3" />,
}

function Steps({ turn, live }: { turn: Turn; live: boolean }) {
  const [open, setOpen] = useState(live)
  useEffect(() => setOpen(live), [live])
  if (turn.steps.length === 0) return null
  return (
    <div className="text-xs text-gray-500 dark:text-gray-400">
      <button
        type="button"
        className="flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-200"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {turn.steps.length} step{turn.steps.length === 1 ? '' : 's'}
      </button>
      {open && (
        <ol className="mt-1 space-y-0.5 border-l border-gray-200 pl-2 dark:border-gray-700">
          {turn.steps.map((step, i) => (
            <li key={i} className="flex items-start gap-1.5">
              <span className="mt-0.5 shrink-0">{STEP_ICON[step.kind] ?? null}</span>
              <span className="line-clamp-3">{step.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

interface ProposalProps {
  turn: Turn
  /** null on the project list: applying makes a new project. */
  projectVersion: number | null
}

/** What a turn would change, and Apply / Discard. */
function Proposal({ turn, projectVersion }: ProposalProps) {
  const markApplied = useAssistantStore((s) => s.markApplied)
  const discard = useAssistantStore((s) => s.discard)
  const newProject = useAssistantStore((s) => s.newProject)
  const edit = useProjectStore((s) => s.edit)
  const loadGenerations = useGenerationStore((s) => s.load)
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const generates = turn.changes.some((c) => c.startsWith('Generating a picture'))

  if (turn.outcome === 'applied')
    return (
      <p className="flex items-center gap-1 text-xs text-green-700 dark:text-green-400">
        <Check className="h-3 w-3" />
        Applied{turn.project_id && projectVersion === null ? ' as a new video' : ''}
      </p>
    )
  if (turn.outcome === 'discarded')
    return (
      <p className="text-xs text-gray-500">
        Discarded{generates && '. The pictures it generated stay in your library.'}
      </p>
    )
  if (turn.outcome !== 'pending' || !turn.proposed_spec) return null

  const stale =
    projectVersion !== null &&
    turn.base_version !== null &&
    turn.base_version !== projectVersion

  async function apply() {
    setBusy(true)
    if (projectVersion === null) {
      const id = await newProject(turn.id)
      setBusy(false)
      if (id) navigate(`/p/${id}`)
      return
    }
    // Into the editor's draft, as an unsaved edit: Save, Discard and History then work
    // on it exactly as they do on a change made by hand.
    edit(turn.proposed_spec!)
    await markApplied(turn.id)
    // The pictures it started are followed by the generations store, which has not
    // seen them: reading the list now picks them up, and fills in any already done.
    if (generates && turn.project_id) void loadGenerations(turn.project_id)
    setBusy(false)
  }

  return (
    <div
      className="space-y-2 rounded border border-primary-200 bg-primary-50/50 p-2 text-xs dark:border-primary-800 dark:bg-primary-900/20"
      aria-label="Proposed changes"
    >
      <ul className="list-disc space-y-0.5 pl-4 text-gray-700 dark:text-gray-300">
        {turn.changes.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
      {generates && (
        <p className="text-gray-500">
          Generated pictures fill in by themselves once this is applied.
        </p>
      )}
      {stale && (
        <p className="text-amber-700 dark:text-amber-300">
          Based on version {turn.base_version}; the project has been saved since (now
          version {projectVersion}). Applying replaces the draft with this proposal.
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          className="btn btn-primary px-2 py-1 text-xs"
          disabled={busy}
          onClick={() => void apply()}
        >
          {projectVersion === null
            ? 'Create this video'
            : stale
              ? 'Apply anyway'
              : 'Apply'}
        </button>
        <button
          type="button"
          className="btn btn-ghost px-2 py-1 text-xs"
          disabled={busy}
          onClick={() => void discard(turn.id)}
        >
          Discard
        </button>
      </div>
    </div>
  )
}

/** The chats about this video, to go back to an earlier one. */
function ChatList({ onPicked }: { onPicked: () => void }) {
  const sessions = useAssistantStore((s) => s.sessions)
  const chat = useAssistantStore((s) => s.chat)
  const openChat = useAssistantStore((s) => s.openChat)
  const removeChat = useAssistantStore((s) => s.removeChat)
  if (sessions.length === 0)
    return <p className="p-3 text-xs text-gray-500">No earlier conversations.</p>
  return (
    <ul
      className="divide-y divide-gray-100 dark:divide-gray-800"
      aria-label="Conversations"
    >
      {sessions.map((s) => (
        <li key={s.id} className="flex items-center gap-1 px-3 py-2 text-xs">
          <button
            type="button"
            className={`min-w-0 flex-1 truncate text-left ${
              chat?.id === s.id ? 'font-semibold' : ''
            }`}
            onClick={() => {
              void openChat(s.id)
              onPicked()
            }}
          >
            {s.title}
          </button>
          <button
            type="button"
            className="btn btn-ghost p-1"
            aria-label={`Delete conversation ${s.title}`}
            onClick={() => void removeChat(s.id)}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function AssistantPanel() {
  const match = useMatch('/p/:id')
  const scope = match?.params.id ?? null
  const open = useAssistantStore((s) => s.open)
  const width = useAssistantStore((s) => s.width)
  const setOpen = useAssistantStore((s) => s.setOpen)
  const setWidth = useAssistantStore((s) => s.setWidth)
  const enter = useAssistantStore((s) => s.enter)
  const chat = useAssistantStore((s) => s.chat)
  const sending = useAssistantStore((s) => s.sending)
  const error = useAssistantStore((s) => s.error)
  const send = useAssistantStore((s) => s.send)
  const stop = useAssistantStore((s) => s.stop)
  const newChat = useAssistantStore((s) => s.newChat)
  const attach = useAssistantStore((s) => s.attach)
  const focus = useAssistantStore((s) => s.focus)
  const project = useProjectStore((s) => s.project)
  const draft = useProjectStore((s) => s.draft)
  const [prompt, setPrompt] = useState('')
  const [showList, setShowList] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void enter(scope)
    setShowList(false)
  }, [scope, enter])

  const turns = useMemo(
    () => Object.fromEntries((chat?.turns ?? []).map((t) => [t.id, t])),
    [chat]
  )
  const running = chat?.turns.find((t) => ACTIVE_TURN.includes(t.status))
  const steps = running?.steps.length ?? 0
  const messageCount = chat?.messages.length ?? 0

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' })
  }, [messageCount, steps])

  // The editor's project, once it has loaded the one this page is about.
  const here = scope && project?.id === scope ? project : null
  const focusLabel =
    here && focus ? draft?.segments.find((s) => s.id === focus)?.label || focus : null

  async function submit() {
    const text = prompt.trim()
    if (!text || sending || running) return
    const ok = await send({
      prompt: text,
      draft_spec: here ? draft : null,
      base_version: here ? here.version : null,
      focus: here ? focus : null,
    })
    if (ok) setPrompt('')
  }

  function startResize(e: React.MouseEvent) {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = width
    const move = (ev: MouseEvent) => setWidth(startWidth + (startX - ev.clientX))
    const up = () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  async function drop(e: React.DragEvent) {
    if (!e.dataTransfer.files.length) return
    e.preventDefault()
    for (const file of Array.from(e.dataTransfer.files)) {
      if (!(await attach({ file }))) break
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-9 shrink-0 flex-col items-center gap-2 border-l border-gray-200 bg-white py-3 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
        aria-label="Open the assistant"
        title="Open the assistant"
      >
        <PanelRightOpen className="h-4 w-4" />
        <span style={{ writingMode: 'vertical-rl' }}>Assistant</span>
        {running && <Loader2 className="h-3 w-3 animate-spin" />}
      </button>
    )
  }

  return (
    <aside
      className="relative flex shrink-0 flex-col border-l border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
      style={{ width }}
      aria-label="Assistant"
      // A file dropped anywhere on the panel is attached, as the paperclip would.
      onDragOver={(e) => e.dataTransfer.types.includes('Files') && e.preventDefault()}
      onDrop={(e) => void drop(e)}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={width}
        className="absolute inset-y-0 -left-1 w-2 cursor-col-resize"
        onMouseDown={startResize}
      />
      <header className="flex items-center gap-1 border-b border-gray-200 px-3 py-2 dark:border-gray-700">
        <Sparkles className="h-4 w-4 text-primary-600" />
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
          {chat?.title || (scope ? 'Assistant' : 'New video from a prompt')}
        </h2>
        <button
          type="button"
          className="btn btn-ghost p-1"
          aria-label="Earlier conversations"
          title="Earlier conversations"
          onClick={() => setShowList(!showList)}
        >
          <History className="h-4 w-4" />
        </button>
        <button
          type="button"
          className="btn btn-ghost p-1"
          aria-label="New conversation"
          title="New conversation"
          onClick={() => {
            newChat()
            setShowList(false)
          }}
        >
          <MessageSquarePlus className="h-4 w-4" />
        </button>
        <button
          type="button"
          className="btn btn-ghost p-1"
          aria-label="Close the assistant"
          onClick={() => setOpen(false)}
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </header>

      {showList ? (
        <div className="flex-1 overflow-auto">
          <ChatList onPicked={() => setShowList(false)} />
        </div>
      ) : (
        <div className="flex-1 space-y-3 overflow-auto p-3 text-sm text-gray-800 dark:text-gray-200">
          {!chat && (
            <div className="space-y-2 text-xs text-gray-600 dark:text-gray-400">
              {scope ? (
                <p>
                  Ask for any change to this video: &ldquo;dissolve into the last
                  scene&rdquo;, &ldquo;find footage of people talking about water for
                  scene 3&rdquo;, &ldquo;change the music after chapter 2 to something
                  calmer&rdquo;. You see what it would change before anything does.
                </p>
              ) : (
                <p>
                  Describe a video and the assistant drafts it from your library: &ldquo;A
                  3-minute video about the Colorado River water wars, using clips where
                  people talk about it.&rdquo; You review the draft before it becomes a
                  project.
                </p>
              )}
              <p>
                Attach a script, a note or a web page with the paperclip and it works from
                that. It keeps working if you close this page.
              </p>
            </div>
          )}
          {chat?.messages.map((m, i) => {
            const turn = m.turn_id ? turns[m.turn_id] : undefined
            if (m.role === 'user') {
              const live = turn && ACTIVE_TURN.includes(turn.status)
              return (
                <div key={i} className="space-y-1">
                  <div className="ml-6 rounded-lg bg-primary-600 px-3 py-2 text-white">
                    <p className="whitespace-pre-wrap">{m.text}</p>
                  </div>
                  {live && turn && (
                    <div className="space-y-1 rounded border border-gray-200 p-2 dark:border-gray-700">
                      <p className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        <span className="flex-1">
                          {turn.status === 'queued'
                            ? 'Waiting to start…'
                            : `${turn.stage || 'Working'}${turn.detail ? `: ${turn.detail}` : ''}`}
                        </span>
                        <button
                          type="button"
                          className="btn btn-ghost px-1 py-0.5 text-xs"
                          onClick={() => void stop(turn.id)}
                        >
                          <Square className="mr-1 inline h-3 w-3" />
                          Stop
                        </button>
                      </p>
                      <Steps turn={turn} live />
                    </div>
                  )}
                </div>
              )
            }
            return (
              <div key={i} className="space-y-1.5">
                <Prose text={m.text} />
                {turn && <Steps turn={turn} live={false} />}
                {turn && (
                  <Proposal
                    turn={turn}
                    projectVersion={scope ? (here?.version ?? null) : null}
                  />
                )}
                {turn?.cost != null && turn.cost > 0 && (
                  <p className="text-[11px] text-gray-400">
                    about {formatCost(turn.cost)} (estimate)
                  </p>
                )}
              </div>
            )
          })}
          {error && (
            <p role="alert" className="text-xs text-red-600 dark:text-red-400">
              {error}
              {/Settings/.test(error) && (
                <>
                  {' '}
                  <Link to="/settings" className="underline">
                    Open Settings
                  </Link>
                </>
              )}
            </p>
          )}
          <div ref={bottom} />
        </div>
      )}

      <footer className="space-y-1 border-t border-gray-200 p-2 dark:border-gray-700">
        <AttachmentList />
        {focusLabel && (
          <p className="truncate text-[11px] text-gray-500">
            &ldquo;This scene&rdquo; means {focusLabel}
          </p>
        )}
        <div className="flex items-end gap-2">
          <AttachControls />
          <textarea
            className="input max-h-40 min-h-[2.5rem] flex-1 resize-y text-sm"
            aria-label="Ask the assistant"
            placeholder={scope ? 'Ask for a change…' : 'Describe a video…'}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void submit()
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary p-2"
            aria-label="Send"
            disabled={!prompt.trim() || sending || !!running || (!!scope && !here)}
            onClick={() => void submit()}
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        {chat && chat.cost > 0 && (
          <p className="text-[11px] text-gray-400">
            This conversation: about {formatCost(chat.cost)} (estimate)
          </p>
        )}
      </footer>
    </aside>
  )
}
