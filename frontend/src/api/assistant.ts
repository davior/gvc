import client from '@/api/client'
import type { VideoSpec } from '@/api/projects'

/**
 * The assistant. A turn is a background job on the server, so nothing here needs the
 * page to stay open: a turn started and left keeps running, and is found again by
 * `sessions` and `attention` on the way back.
 */

export type TurnStatus = 'queued' | 'processing' | 'done' | 'error' | 'cancelled'

export interface TurnStep {
  kind: 'think' | 'search' | 'edit' | 'issue' | 'note'
  text: string
}

export interface Turn {
  id: string
  session_id: string
  project_id: string | null
  status: TurnStatus
  stage: string
  detail: string
  error: string | null
  prompt: string
  steps: TurnStep[]
  reply: string
  /** The whole proposed spec, while the proposal waits for Apply or Discard. */
  proposed_spec: VideoSpec | null
  changes: string[]
  outcome: '' | 'pending' | 'applied' | 'discarded'
  /** The project version the turn was asked about. */
  base_version: number | null
  cost: number | null
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  turn_id: string | null
  at: string | null
}

export interface ChatSummary {
  id: string
  project_id: string | null
  title: string
  created_at: string
  updated_at: string
}

export type AttachmentKind = 'file' | 'note' | 'url' | 'image'

/** Material the conversation works from: text read when it was attached, or a picture. */
export interface Attachment {
  id: string
  kind: AttachmentKind
  title: string
  /** The file name, the note's id, or the page's URL after redirects. */
  source: string
  chars: number
  /** Longer than one attachment may be, so only its beginning was kept. */
  truncated: boolean
  preview: string
  /** Pictures only: a small data URL to show, and the size the model is sent. */
  thumb?: string | null
  width?: number | null
  height?: number | null
  added_at: string | null
}

/** A note in Gecko Notes, to pick one to attach. */
export interface NoteChoice {
  id: string
  title: string
  preview: string
  modified_at: string | null
}

export interface Chat extends ChatSummary {
  messages: ChatMessage[]
  attachments: Attachment[]
  turns: Turn[]
  cost: number
}

export interface TurnRequest {
  prompt: string
  session_id?: string | null
  project_id?: string | null
  draft_spec?: VideoSpec | null
  base_version?: number | null
  focus?: string | null
}

export const ACTIVE_TURN: TurnStatus[] = ['queued', 'processing']

interface DataResponse<T> {
  data: T
}

interface ListResponse<T> {
  data: T[]
  total: number
}

export const assistantApi = {
  sessions(projectId: string | null): Promise<ChatSummary[]> {
    return client
      .get<ListResponse<ChatSummary>>('/assistant/sessions', {
        params: projectId ? { project_id: projectId } : {},
      })
      .then((r) => r.data.data)
  },

  session(id: string): Promise<Chat> {
    return client
      .get<DataResponse<Chat>>(`/assistant/sessions/${id}`)
      .then((r) => r.data.data)
  },

  /** An empty conversation, to attach material to before the first request. */
  createSession(projectId: string | null): Promise<Chat> {
    return client
      .post<DataResponse<Chat>>('/assistant/sessions', { project_id: projectId })
      .then((r) => r.data.data)
  },

  attachFile(sessionId: string, file: File): Promise<Attachment> {
    const form = new FormData()
    form.append('file', file)
    // The client's JSON default would make axios serialise the form as JSON; this
    // makes it send multipart, with the browser filling in the boundary.
    return client
      .post<DataResponse<Attachment>>(
        `/assistant/sessions/${sessionId}/attachments/file`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      )
      .then((r) => r.data.data)
  },

  attachNote(sessionId: string, noteId: string): Promise<Attachment> {
    return client
      .post<DataResponse<Attachment>>(
        `/assistant/sessions/${sessionId}/attachments/note`,
        {
          note_id: noteId,
        }
      )
      .then((r) => r.data.data)
  },

  attachUrl(sessionId: string, url: string): Promise<Attachment> {
    return client
      .post<DataResponse<Attachment>>(
        `/assistant/sessions/${sessionId}/attachments/url`,
        {
          url,
        }
      )
      .then((r) => r.data.data)
  },

  detach(sessionId: string, attachmentId: string): Promise<void> {
    return client
      .delete(`/assistant/sessions/${sessionId}/attachments/${attachmentId}`)
      .then(() => undefined)
  },

  /** The user's notes in Gecko Notes, newest first, matching `q` when given. */
  findNotes(q: string): Promise<NoteChoice[]> {
    return client
      .get<ListResponse<NoteChoice>>('/assistant/notes', { params: q ? { q } : {} })
      .then((r) => r.data.data)
  },

  removeSession(id: string): Promise<void> {
    return client.delete(`/assistant/sessions/${id}`).then(() => undefined)
  },

  start(body: TurnRequest): Promise<Turn> {
    return client
      .post<DataResponse<Turn>>('/assistant/turns', body)
      .then((r) => r.data.data)
  },

  stop(id: string): Promise<Turn> {
    return client
      .delete<DataResponse<Turn>>(`/assistant/turns/${id}`)
      .then((r) => r.data.data)
  },

  applied(id: string): Promise<Turn> {
    return client
      .post<DataResponse<Turn>>(`/assistant/turns/${id}/applied`)
      .then((r) => r.data.data)
  },

  discarded(id: string): Promise<Turn> {
    return client
      .post<DataResponse<Turn>>(`/assistant/turns/${id}/discarded`)
      .then((r) => r.data.data)
  },

  newProject(id: string): Promise<string> {
    return client
      .post<DataResponse<{ project_id: string }>>(`/assistant/turns/${id}/new-project`)
      .then((r) => r.data.data.project_id)
  },

  /** What is running, or finished with a proposal nobody has acted on yet. */
  attention(): Promise<Turn[]> {
    return client
      .get<ListResponse<Turn>>('/assistant/turns', { params: { attention: true } })
      .then((r) => r.data.data)
  },
}
