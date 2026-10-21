import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { assistantApi, type Attachment, type Chat, type Turn } from '@/api/assistant'
import type { Project, VideoSpec } from '@/api/projects'
import AssistantPanel from '@/components/AssistantPanel'
import { useAssistantStore } from '@/stores/assistant'
import { useProjectStore } from '@/stores/projects'

const spec: VideoSpec = {
  title: 'Water Wars',
  segments: [{ id: 's_valley', kind: 'scene', label: 'The valley' }],
}

const project = {
  id: 'p1',
  title: 'Water Wars',
  origin: 'blank',
  version: 3,
  created_at: '',
  updated_at: '',
  spec,
} as unknown as Project

function turn(overrides: Partial<Turn> = {}): Turn {
  return {
    id: 't1',
    session_id: 'c1',
    project_id: 'p1',
    status: 'done',
    stage: '',
    detail: '',
    error: null,
    prompt: 'dissolve into the valley',
    steps: [{ kind: 'edit', text: 'Done: Changed The valley: transition_in.' }],
    reply: 'Dissolve into the valley now.',
    proposed_spec: {
      ...spec,
      segments: [{ ...spec.segments[0], transition_in: { style: 'dissolve' } }],
    },
    changes: ['Changed The valley: transition_in'],
    outcome: 'pending',
    base_version: 3,
    cost: 0.0123,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

function chat(t: Turn): Chat {
  return {
    id: 'c1',
    project_id: t.project_id,
    title: 'dissolve into the valley',
    created_at: '',
    updated_at: '',
    cost: t.cost ?? 0,
    attachments: [],
    turns: [t],
    messages: [
      { role: 'user', text: t.prompt, turn_id: t.id, at: null },
      ...(t.status === 'done'
        ? [{ role: 'assistant' as const, text: t.reply, turn_id: t.id, at: null }]
        : []),
    ],
  }
}

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/p/:id" element={<AssistantPanel />} />
        <Route path="/projects" element={<AssistantPanel />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  localStorage.clear()
  useAssistantStore.getState().reset()
  useAssistantStore.setState({ open: true })
  useProjectStore.setState({ project, draft: spec, dirty: false })
  vi.spyOn(assistantApi, 'attention').mockResolvedValue([])
})
afterEach(() => vi.restoreAllMocks())

describe('AssistantPanel', () => {
  it('finds a finished proposal on the way back and applies it into the draft', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(turn())])
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce(chat(turn()))
      .mockResolvedValue(chat(turn({ outcome: 'applied', proposed_spec: null })))
    const applied = vi.spyOn(assistantApi, 'applied').mockResolvedValue(turn())
    at('/p/p1')

    expect(await screen.findByText('Dissolve into the valley now.')).toBeInTheDocument()
    expect(screen.getByText('Changed The valley: transition_in')).toBeInTheDocument()
    // The turn and the conversation each say their cost.
    expect(screen.getAllByText(/about \$0\.01 \(estimate\)/)).toHaveLength(2)

    await userEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(useProjectStore.getState().draft?.segments[0].transition_in).toEqual({
      style: 'dissolve',
    })
    expect(useProjectStore.getState().dirty).toBe(true)
    expect(applied).toHaveBeenCalledWith('t1')
    expect(await screen.findByText(/Applied/)).toBeInTheDocument()
  })

  it('warns when the project was saved after the request was made', async () => {
    useProjectStore.setState({ project: { ...project, version: 5 } })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(turn())])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(turn()))
    at('/p/p1')
    expect(await screen.findByText(/Based on version 3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply anyway' })).toBeInTheDocument()
  })

  it('sends the draft, its version and the focused scene, and shows the live steps', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    const running = turn({
      status: 'processing',
      stage: 'Working',
      detail: 'searching the library',
      steps: [{ kind: 'search', text: "Searching the library: 'water'" }],
      outcome: '',
      proposed_spec: null,
    })
    const start = vi.spyOn(assistantApi, 'start').mockResolvedValue(running)
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(running))
    const stop = vi.spyOn(assistantApi, 'stop').mockResolvedValue(running)
    useAssistantStore.setState({ focus: 's_valley' })
    at('/p/p1')
    await waitFor(() => expect(assistantApi.sessions).toHaveBeenCalledWith('p1'))
    useAssistantStore.setState({ focus: 's_valley' })

    expect(await screen.findByText(/means The valley/)).toBeInTheDocument()
    await userEvent.type(
      screen.getByLabelText('Ask the assistant'),
      'dissolve into this{Enter}'
    )
    expect(start).toHaveBeenCalledWith({
      prompt: 'dissolve into this',
      draft_spec: spec,
      base_version: 3,
      focus: 's_valley',
      session_id: null,
      project_id: 'p1',
    })
    expect(await screen.findByText(/Working: searching the library/)).toBeInTheDocument()
    expect(screen.getByText("Searching the library: 'water'")).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Stop/ }))
    expect(stop).toHaveBeenCalledWith('t1')
  })

  it('on the project list, a draft becomes a new video', async () => {
    const draft = turn({ project_id: null })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(draft)])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(draft))
    const made = vi.spyOn(assistantApi, 'newProject').mockResolvedValue('p9')
    at('/projects')
    await userEvent.click(
      await screen.findByRole('button', { name: 'Create this video' })
    )
    expect(made).toHaveBeenCalledWith('t1')
  })

  it('collapses to a strip and remembers it', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    at('/projects')
    await userEvent.click(screen.getByRole('button', { name: 'Close the assistant' }))
    expect(screen.getByRole('button', { name: 'Open the assistant' })).toBeInTheDocument()
    expect(localStorage.getItem('gvc-assistant-open')).toBe('0')
  })

  it('attaches a web page to a new conversation, lists it and removes it', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    const empty: Chat = { ...chat(turn()), turns: [], messages: [], title: '' }
    const page: Attachment = {
      id: 'a1',
      kind: 'url',
      title: 'The dry river',
      source: 'https://news.example/river',
      chars: 12000,
      truncated: false,
      preview: 'It last reached the sea in 1998.',
      added_at: null,
    }
    const created = vi.spyOn(assistantApi, 'createSession').mockResolvedValue(empty)
    const attached = vi.spyOn(assistantApi, 'attachUrl').mockResolvedValue(page)
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce({ ...empty, attachments: [page] })
      .mockResolvedValue(empty)
    const detached = vi.spyOn(assistantApi, 'detach').mockResolvedValue()
    at('/p/p1')
    await waitFor(() => expect(assistantApi.sessions).toHaveBeenCalledWith('p1'))

    await userEvent.click(screen.getByRole('button', { name: 'Attach' }))
    await userEvent.click(screen.getByRole('menuitem', { name: /A web page/ }))
    await userEvent.type(
      screen.getByLabelText('Web page address'),
      'news.example/river{Enter}'
    )
    expect(created).toHaveBeenCalledWith('p1')
    expect(attached).toHaveBeenCalledWith('c1', 'news.example/river')
    expect(await screen.findByText('The dry river')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove The dry river' }))
    expect(detached).toHaveBeenCalledWith('c1', 'a1')
    await waitFor(() =>
      expect(screen.queryByText('The dry river')).not.toBeInTheDocument()
    )
  })

  it('finds a note in Gecko Notes and attaches it', async () => {
    const open = chat(turn({ outcome: 'applied', proposed_spec: null }))
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([open])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(open)
    const find = vi
      .spyOn(assistantApi, 'findNotes')
      .mockResolvedValue([
        {
          id: 'n1',
          title: 'Colorado research',
          preview: 'The compact of 1922',
          modified_at: null,
        },
      ])
    const attached = vi.spyOn(assistantApi, 'attachNote').mockResolvedValue({
      id: 'a2',
      kind: 'note',
      title: 'Colorado research',
      source: 'n1',
      chars: 300,
      truncated: false,
      preview: '',
      added_at: null,
    })
    at('/p/p1')
    await screen.findByText('Dissolve into the valley now.')

    await userEvent.click(screen.getByRole('button', { name: 'Attach' }))
    await userEvent.click(
      screen.getByRole('menuitem', { name: /A note from Gecko Notes/ })
    )
    await userEvent.type(screen.getByLabelText('Search your notes'), 'colorado')
    // Typing searches once it pauses, not per keystroke.
    await waitFor(() => expect(find).toHaveBeenLastCalledWith('colorado'))
    expect(find).not.toHaveBeenCalledWith('c')
    await userEvent.click(
      await screen.findByRole('button', { name: /Colorado research/ })
    )
    // An open conversation takes it; no new one is made.
    expect(attached).toHaveBeenCalledWith('c1', 'n1')
  })

  it('points at Settings when no provider is set up', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    vi.spyOn(assistantApi, 'start').mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: 'no_provider',
            message: 'Set up an AI provider in Settings first.',
          },
        },
      },
    })
    at('/projects')
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'a video{Enter}')
    expect(await screen.findByRole('link', { name: 'Open Settings' })).toBeInTheDocument()
  })
})
