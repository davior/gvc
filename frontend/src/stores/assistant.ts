import { create } from 'zustand'
import { apiErrorMessage } from '@/api/client'
import {
  ACTIVE_TURN,
  assistantApi,
  type Chat,
  type ChatSummary,
  type Turn,
  type TurnRequest,
} from '@/api/assistant'

/**
 * The assistant panel's state: which video it is about (`scope`), its conversations,
 * and the one open.
 *
 * A turn runs on the server, so this only follows it. While the open conversation has
 * a turn running, the conversation is re-read every second and a half; the poll is one
 * timer re-armed after each answer, and every answer is checked against a token so a
 * conversation left mid-turn can't have its steps land on the next one.
 */

const POLL_MS = 1500
const OPEN_KEY = 'gvc-assistant-open'
const WIDTH_KEY = 'gvc-assistant-width'
export const MIN_WIDTH = 280
export const MAX_WIDTH = 640

function stored<T>(key: string, fallback: T, parse: (raw: string) => T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : parse(raw)
  } catch {
    return fallback
  }
}

function keep(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* a private window: the panel just forgets */
  }
}

interface AssistantState {
  open: boolean
  width: number
  /** The project the panel is about; null on the project list (a new video). */
  scope: string | null
  sessions: ChatSummary[]
  chat: Chat | null
  sending: boolean
  /** A file, note or page is being read in. */
  attaching: boolean
  error: string | null
  /** Turns running, or waiting for Apply, anywhere: the header's marker. */
  attention: Turn[]
  /** The scene last worked on in the editor: "this scene". */
  focus: string | null

  setOpen: (open: boolean) => void
  setWidth: (width: number) => void
  setFocus: (segmentId: string | null) => void
  enter: (scope: string | null) => Promise<void>
  openChat: (id: string) => Promise<void>
  newChat: () => void
  send: (request: Omit<TurnRequest, 'session_id' | 'project_id'>) => Promise<boolean>
  attach: (what: AttachRequest) => Promise<boolean>
  detach: (attachmentId: string) => Promise<void>
  stop: (turnId: string) => Promise<void>
  markApplied: (turnId: string) => Promise<void>
  discard: (turnId: string) => Promise<void>
  newProject: (turnId: string) => Promise<string | null>
  refreshAttention: () => Promise<void>
  removeChat: (id: string) => Promise<void>
  reset: () => void
}

export type AttachRequest = { file: File } | { noteId: string } | { url: string }

let token = 0
let timer: ReturnType<typeof setTimeout> | null = null

function stopPolling() {
  if (timer) clearTimeout(timer)
  timer = null
}

export const useAssistantStore = create<AssistantState>((set, get) => {
  function running(chat: Chat | null): Turn | undefined {
    return chat?.turns.find((t) => ACTIVE_TURN.includes(t.status))
  }

  function poll(mine: number) {
    stopPolling()
    const chat = get().chat
    if (!chat || !running(chat)) return
    timer = setTimeout(async () => {
      try {
        const fresh = await assistantApi.session(chat.id)
        if (mine !== token) return
        set({ chat: fresh })
        if (!running(fresh)) {
          void get().refreshAttention()
          return
        }
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
      poll(mine)
    }, POLL_MS)
  }

  async function reload(mine: number, id: string) {
    const fresh = await assistantApi.session(id)
    if (mine !== token) return
    set({ chat: fresh })
    poll(mine)
  }

  return {
    open: stored(OPEN_KEY, true, (raw) => raw === '1'),
    width: stored(WIDTH_KEY, 360, (raw) =>
      Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Number(raw) || 360))
    ),
    scope: null,
    sessions: [],
    chat: null,
    sending: false,
    attaching: false,
    error: null,
    attention: [],
    focus: null,

    setOpen(open) {
      keep(OPEN_KEY, open ? '1' : '0')
      set({ open })
    },

    setWidth(width) {
      const clamped = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)))
      keep(WIDTH_KEY, String(clamped))
      set({ width: clamped })
    },

    setFocus(focus) {
      set({ focus })
    },

    async enter(scope) {
      const mine = ++token
      stopPolling()
      set({ scope, sessions: [], chat: null, error: null, focus: null, attaching: false })
      try {
        const sessions = await assistantApi.sessions(scope)
        if (mine !== token) return
        set({ sessions })
        // The latest conversation, so coming back to a video finds where it was left,
        // a turn still running or a proposal still waiting.
        if (sessions[0]) await reload(mine, sessions[0].id)
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
    },

    async openChat(id) {
      const mine = ++token
      stopPolling()
      set({ error: null })
      try {
        await reload(mine, id)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    newChat() {
      token += 1
      stopPolling()
      set({ chat: null, error: null, attaching: false })
    },

    async send(request) {
      const mine = token
      const { chat, scope } = get()
      set({ sending: true, error: null })
      try {
        const turn = await assistantApi.start({
          ...request,
          session_id: chat?.id ?? null,
          project_id: scope,
        })
        if (mine !== token) return false
        await reload(mine, turn.session_id)
        if (mine !== token) return false
        const sessions = await assistantApi.sessions(scope)
        if (mine !== token) return false
        set({ sessions, sending: false })
        void get().refreshAttention()
        return true
      } catch (error) {
        if (mine !== token) return false
        set({ sending: false, error: apiErrorMessage(error) })
        return false
      }
    },

    async stop(turnId) {
      const mine = token
      try {
        await assistantApi.stop(turnId)
        const chat = get().chat
        if (mine === token && chat) await reload(mine, chat.id)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async markApplied(turnId) {
      const mine = token
      try {
        await assistantApi.applied(turnId)
        const chat = get().chat
        if (mine === token && chat) await reload(mine, chat.id)
        void get().refreshAttention()
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async discard(turnId) {
      const mine = token
      try {
        await assistantApi.discarded(turnId)
        const chat = get().chat
        if (mine === token && chat) await reload(mine, chat.id)
        void get().refreshAttention()
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async newProject(turnId) {
      const mine = token
      try {
        const projectId = await assistantApi.newProject(turnId)
        void get().refreshAttention()
        return mine === token ? projectId : null
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
        return null
      }
    },

    async attach(what) {
      const mine = token
      set({ attaching: true, error: null })
      try {
        let chat = get().chat
        // Material can come before the first request, so a new conversation is made
        // to hold it; the first request then continues it.
        if (!chat) {
          chat = await assistantApi.createSession(get().scope)
          if (mine !== token) return false
          set({ chat, sessions: [chat, ...get().sessions] })
        }
        if ('file' in what) await assistantApi.attachFile(chat.id, what.file)
        else if ('noteId' in what) await assistantApi.attachNote(chat.id, what.noteId)
        else await assistantApi.attachUrl(chat.id, what.url)
        if (mine !== token) return false
        await reload(mine, chat.id)
        return mine === token
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
        return false
      } finally {
        if (mine === token) set({ attaching: false })
      }
    },

    async detach(attachmentId) {
      const mine = token
      const chat = get().chat
      if (!chat) return
      try {
        await assistantApi.detach(chat.id, attachmentId)
        if (mine === token) await reload(mine, chat.id)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async refreshAttention() {
      try {
        set({ attention: await assistantApi.attention() })
      } catch {
        /* the marker is a nicety; the panel says what is wrong */
      }
    },

    async removeChat(id) {
      const mine = token
      try {
        await assistantApi.removeSession(id)
        if (mine !== token) return
        const wasOpen = get().chat?.id === id
        set({
          sessions: get().sessions.filter((s) => s.id !== id),
          ...(wasOpen ? { chat: null } : {}),
        })
        if (wasOpen) stopPolling()
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    reset() {
      token += 1
      stopPolling()
      set({
        scope: null,
        sessions: [],
        chat: null,
        sending: false,
        attaching: false,
        error: null,
        attention: [],
        focus: null,
      })
    },
  }
})
