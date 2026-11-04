import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { assistantApi } from '@/api/assistant'
import type { LiveDictationEvent } from '@/api/suiteSpeech'
import AssistantPanel from '@/components/AssistantPanel'
import { useAssistantStore } from '@/stores/assistant'
import { useProjectStore } from '@/stores/projects'

/**
 * Dictation into the assistant's prompt (SV-7). The suite's stream is faked at the module
 * boundary; the browser's microphone and recorder are faked as globals.
 */

const stream = vi.hoisted(() => ({
  ready: true,
  onEvent: null as null | ((e: LiveDictationEvent) => void),
  onClose: null as null | ((code: number, reason: string) => void),
  stopped: 0,
  chunks: 0,
}))

vi.mock('@/api/suiteSpeech', () => ({
  suiteSpeechApi: { ready: () => Promise.resolve(stream.ready) },
  connectLiveDictation: (
    onEvent: (e: LiveDictationEvent) => void,
    onClose: (code: number, reason: string) => void
  ) => {
    stream.onEvent = onEvent
    stream.onClose = onClose
    return {
      sendAudioChunk: () => {
        stream.chunks += 1
      },
      stop: () => {
        stream.stopped += 1
        onClose(1000, '')
      },
      close: () => undefined,
    }
  },
}))

class FakeRecorder {
  static isTypeSupported = () => true
  state = 'inactive'
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['last']) })
    this.onstop?.()
  }
}

function open() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <Routes>
        <Route path="/projects" element={<AssistantPanel />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  Object.assign(stream, {
    ready: true,
    onEvent: null,
    onClose: null,
    stopped: 0,
    chunks: 0,
  })
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: () =>
        Promise.resolve({ getTracks: () => [{ stop: () => undefined }] }),
    },
  })
  localStorage.clear()
  useAssistantStore.getState().reset()
  useAssistantStore.setState({ open: true })
  useProjectStore.setState({ project: null, draft: null, dirty: false })
  vi.spyOn(assistantApi, 'attention').mockResolvedValue([])
  vi.spyOn(assistantApi, 'personas').mockResolvedValue([])
  vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('dictating into the assistant', () => {
  it('shows words as they are heard and adds each phrase to what is typed, without sending', async () => {
    const start = vi.spyOn(assistantApi, 'start')
    open()
    const box = screen.getByLabelText('Ask the assistant')
    await userEvent.type(box, 'Make a video')

    await userEvent.click(await screen.findByRole('button', { name: 'Dictate' }))
    expect(screen.getByRole('button', { name: 'Stop dictating' })).toHaveAttribute(
      'aria-pressed',
      'true'
    )

    act(() => stream.onEvent?.({ type: 'interim', text: 'about the' }))
    expect(screen.getByText('about the…')).toBeInTheDocument()
    act(() => stream.onEvent?.({ type: 'final', text: 'about the river' }))

    expect(box).toHaveValue('Make a video about the river')
    expect(screen.queryByText('about the…')).not.toBeInTheDocument()
    expect(start).not.toHaveBeenCalled()

    // Stopping sends the recorder's last chunk first, then asks the suite to flush.
    await userEvent.click(screen.getByRole('button', { name: 'Stop dictating' }))
    expect(stream.chunks).toBe(1)
    expect(stream.stopped).toBe(1)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Dictate' })).toBeInTheDocument()
    )
  })

  it('says why when the connection ends without being asked to', async () => {
    open()
    await userEvent.click(await screen.findByRole('button', { name: 'Dictate' }))
    act(() =>
      stream.onClose?.(
        4400,
        'No Deepgram key is set up in Gecko Suite, so dictation is off.'
      )
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('No Deepgram key')
  })

  it('offers no microphone when the suite cannot transcribe', async () => {
    stream.ready = false
    open()
    await screen.findByLabelText('Ask the assistant')
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Dictate' })).not.toBeInTheDocument()
    )
  })
})
