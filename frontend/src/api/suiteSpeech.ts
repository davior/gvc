import axios from 'axios'
import { readToken } from '@/api/client'
import { currentConfig, loadConfig } from '@/api/config'

/**
 * Live dictation from Gecko Suite (SV-7): the microphone streamed to the suite, which relays
 * it to Deepgram with its own key and sends the words back as they are heard.
 *
 * Ported from Gecko Notes' `api/deepgramStream.ts`; the protocol is the same, only the
 * address differs (the suite's stream, not Notes' own). The browser talks to the suite
 * directly, as GVC's person: a websocket cannot set headers, so the token goes in the query,
 * and the suite checks it and this page's origin.
 */

export type LiveDictationEvent =
  | { type: 'interim'; text: string }
  | { type: 'final'; text: string }
  | { type: 'error'; message: string }

export interface LiveDictationHandle {
  /** One MediaRecorder chunk, as a binary frame. */
  sendAudioChunk: (chunk: Blob) => void
  /** Stop speaking: the suite flushes the last words, then closes. */
  stop: () => void
  /** Close at once, nothing flushed (unmount). */
  close: () => void
}

/** The suite's close codes, as sentences. */
export const CLOSE_MESSAGES: Record<number, string> = {
  4400: 'No Deepgram key is set up in Gecko Suite, so dictation is off.',
  4401: 'Your session has ended. Sign in again to dictate.',
  4403: 'Gecko Suite refused this page. Its CORS_ORIGIN must list Video Creator.',
  4409: 'You are already dictating somewhere else. Stop there first.',
}

function suiteBase(): string {
  return (currentConfig()?.suite_base_url ?? '').replace(/\/+$/, '')
}

export function streamUrl(base: string, token: string): string {
  const ws = base.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  return `${ws}/api/v1/ai/speech/stt/stream?app=gvc&token=${encodeURIComponent(token)}`
}

const http = axios.create()

export const suiteSpeechApi = {
  /** Whether the suite has a Deepgram key for this person: the microphone shows only then. */
  async ready(): Promise<boolean> {
    const config = await loadConfig()
    if (config.ai_backend !== 'suite' || !config.suite_base_url) return false
    const token = readToken()
    const res = await http.get<{ data: { ready: boolean } }>(
      `${suiteBase()}/api/v1/ai/speech/stt/ready`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} }
    )
    return res.data.data.ready === true
  },
}

export function connectLiveDictation(
  onEvent: (event: LiveDictationEvent) => void,
  onClose: (code: number, reason: string) => void
): LiveDictationHandle {
  const ws = new WebSocket(streamUrl(suiteBase(), readToken() ?? ''))
  // The recorder starts at once, but the handshake takes a moment. The first chunk carries
  // the audio container's header; dropped, Deepgram cannot decode the rest (Notes learnt
  // this in production), so chunks wait here until the socket is open.
  const pending: Blob[] = []
  let stopRequested = false

  ws.onopen = () => {
    for (const chunk of pending) ws.send(chunk)
    pending.length = 0
    if (stopRequested) ws.send(JSON.stringify({ type: 'stop' }))
  }
  ws.onmessage = (event) => {
    if (typeof event.data !== 'string') return
    try {
      onEvent(JSON.parse(event.data) as LiveDictationEvent)
    } catch {
      /* not ours */
    }
  }
  ws.onclose = (event) => onClose(event.code, CLOSE_MESSAGES[event.code] ?? '')

  return {
    sendAudioChunk(chunk) {
      if (ws.readyState === WebSocket.OPEN) ws.send(chunk)
      else if (ws.readyState === WebSocket.CONNECTING) pending.push(chunk)
    },
    stop() {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'stop' }))
      else if (ws.readyState === WebSocket.CONNECTING) stopRequested = true
    },
    close() {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
        ws.close()
    },
  }
}
