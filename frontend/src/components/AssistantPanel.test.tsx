import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { assistantApi, type Attachment, type Chat, type Turn } from '@/api/assistant'
import type { Project, VideoSpec } from '@/api/projects'
import { recipesApi, type Recipe } from '@/api/recipes'
import { themesApi } from '@/api/themes'
import AssistantPanel from '@/components/AssistantPanel'
import { useRecipeStore } from '@/stores/recipes'
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
    persona_id: null,
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
  vi.spyOn(assistantApi, 'personas').mockResolvedValue([])
  useRecipeStore.getState().reset()
  vi.spyOn(recipesApi, 'list').mockResolvedValue([])
  vi.spyOn(themesApi, 'list').mockResolvedValue([])
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

  it('offers a proposed note on its own, creates it on its button, and links to it', async () => {
    const note = {
      note_ref: 'n1',
      title: 'River research',
      markdown: '# River\n\nThe **water** is gone.',
      folder: null,
      state: 'pending' as const,
      note_url: null,
    }
    const asked = turn({
      proposed_spec: null,
      changes: [],
      outcome: '',
      reply: 'A note for Gecko Notes, ready to create.',
      notes: [note],
    })
    const made = turn({
      ...asked,
      notes: [{ ...note, state: 'created', note_url: 'https://notes.test/notes/x' }],
    })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(asked)])
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce(chat(asked))
      .mockResolvedValue(chat(made))
    const create = vi.spyOn(assistantApi, 'createNote').mockResolvedValue(made)
    at('/p/p1')

    const card = await screen.findByLabelText('Note: River research')
    expect(card).toHaveTextContent('folder “From Video Creator”')
    // A note is not an edit to the video, so there is nothing to apply in the editor.
    expect(screen.queryByRole('button', { name: 'Apply' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Read it' }))
    expect(screen.getByLabelText('Text of River research')).toHaveTextContent(
      'The water is gone.'
    )

    await userEvent.click(screen.getByRole('button', { name: 'Create in Gecko Notes' }))
    expect(create).toHaveBeenCalledWith('t1', 'n1')
    expect(
      await screen.findByRole('link', { name: 'Open in Gecko Notes' })
    ).toHaveAttribute('href', 'https://notes.test/notes/x')
    expect(useProjectStore.getState().dirty).toBe(false)
  })

  it('offers a playlist change on its own and makes it in GAM on its button', async () => {
    const proposal = {
      playlist_ref: 'pl1',
      playlist_id: 'p9',
      name: 'The financial crisis',
      description: null,
      add: [
        {
          asset_id: 'v2',
          name: 'Street',
          type: 'video',
          in_point: 61,
          out_point: 64,
          image_seconds: null,
          label: 'Queues',
          note: null,
        },
      ],
      remove: [{ item_id: 'it-2', name: 'Map', label: null }],
      state: 'pending' as const,
      skipped: [],
      playlist_url: null,
    }
    const asked = turn({
      proposed_spec: null,
      changes: [],
      outcome: '',
      playlists: [proposal],
    })
    const made = turn({
      ...asked,
      playlists: [
        {
          ...proposal,
          state: 'applied',
          skipped: ['Map: already gone from the playlist.'],
          playlist_url: 'https://gam.test/playlists/p9',
        },
      ],
    })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(asked)])
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce(chat(asked))
      .mockResolvedValue(chat(made))
    const apply = vi.spyOn(assistantApi, 'applyPlaylist').mockResolvedValue(made)
    at('/p/p1')

    const card = await screen.findByLabelText('Playlist: The financial crisis')
    expect(card).toHaveTextContent('add 1, remove 1 items')
    // Not an edit to the video: nothing to apply in the editor.
    expect(screen.queryByRole('button', { name: 'Apply' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Show the items' }))
    expect(screen.getByLabelText('Changes to The financial crisis')).toHaveTextContent(
      'Queues (Street) · 1:01–1:04'
    )

    await userEvent.click(screen.getByRole('button', { name: 'Change in GAM' }))
    expect(apply).toHaveBeenCalledWith('t1', 'pl1')
    expect(await screen.findByRole('link', { name: 'Open in GAM' })).toHaveAttribute(
      'href',
      'https://gam.test/playlists/p9'
    )
    expect(screen.getByText('Map: already gone from the playlist.')).toBeInTheDocument()
    expect(useProjectStore.getState().dirty).toBe(false)
  })

  it('draws a reply written in Markdown instead of showing its marks', async () => {
    const t = turn({ reply: 'Two **scenes** change:\n\n- The valley\n- The river' })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(t)])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(t))
    at('/p/p1')

    expect((await screen.findByText('scenes')).tagName).toBe('STRONG')
    // A list item of its own, not a dash at the start of a line. (The proposal below
    // has list items too, so this names the reply's.)
    expect(screen.getByText('The river').tagName).toBe('LI')
    expect(screen.queryByText(/\*\*/)).toBeNull()
  })

  it('warns when the project was saved after the request was made', async () => {
    useProjectStore.setState({ project: { ...project, version: 5 } })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(turn())])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(turn()))
    at('/p/p1')
    expect(await screen.findByText(/Based on version 3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Apply anyway' })).toBeInTheDocument()
  })

  it('holds a request while the draft has unsaved changes, and sends it once saved', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    const running = turn({ status: 'processing', outcome: '', proposed_spec: null })
    const start = vi.spyOn(assistantApi, 'start').mockResolvedValue(running)
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(running))
    useProjectStore.setState({ dirty: true })
    at('/p/p1')
    await waitFor(() => expect(assistantApi.sessions).toHaveBeenCalledWith('p1'))

    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'add a title{Enter}')
    expect(start).not.toHaveBeenCalled()
    expect(await screen.findByText(/unsaved changes/)).toBeInTheDocument()
    // The request stays typed, ready to send again.
    expect(screen.getByLabelText('Ask the assistant')).toHaveValue('add a title')

    // Saving (or discarding) clears the notice, and the same request now goes through.
    useProjectStore.setState({ dirty: false })
    await waitFor(() => expect(screen.queryByText(/unsaved changes/)).toBeNull())
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(start).toHaveBeenCalledTimes(1)
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
      persona_id: null,
      auto_run: false,
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

  it('attaches a picture and shows its thumbnail', async () => {
    const open = chat(turn({ outcome: 'applied', proposed_spec: null }))
    const picture: Attachment = {
      id: 'a3',
      kind: 'image',
      title: 'board.jpg',
      source: 'board.jpg',
      chars: 0,
      truncated: false,
      preview: '',
      thumb: 'data:image/jpeg;base64,AAAA',
      width: 1568,
      height: 1045,
      added_at: null,
    }
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([open])
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce(open)
      .mockResolvedValue({ ...open, attachments: [picture] })
    const attached = vi.spyOn(assistantApi, 'attachFile').mockResolvedValue(picture)
    const { container } = at('/p/p1')
    await screen.findByText('Dissolve into the valley now.')

    const file = new File(['x'], 'board.jpg', { type: 'image/jpeg' })
    await userEvent.upload(screen.getByLabelText('Attach files'), file)
    expect(attached).toHaveBeenCalledWith('c1', file)
    expect(await screen.findByText('board.jpg')).toBeInTheDocument()
    expect(
      container.querySelector('img[src="data:image/jpeg;base64,AAAA"]')
    ).not.toBeNull()
    expect(screen.getByText('board.jpg').closest('li')?.title).toContain('1568×1045')
  })

  it('finds a note in Gecko Notes and attaches it', async () => {
    const open = chat(turn({ outcome: 'applied', proposed_spec: null }))
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([open])
    vi.spyOn(assistantApi, 'session').mockResolvedValue(open)
    const find = vi.spyOn(assistantApi, 'findNotes').mockResolvedValue([
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

  it('offers a persona picker only when the suite has personas, and asks as the one chosen', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    vi.spyOn(assistantApi, 'personas').mockResolvedValue([
      {
        id: 'p-doc',
        name: 'Documentarian',
        description: 'Plain and sober.',
        avatar: null,
      },
    ])
    const running = turn({ status: 'processing', outcome: '', proposed_spec: null })
    const start = vi.spyOn(assistantApi, 'start').mockResolvedValue(running)
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(running))
    at('/p/p1')
    const picker = await screen.findByRole('combobox', { name: 'Persona' })
    await userEvent.selectOptions(picker, 'p-doc')
    await userEvent.type(
      screen.getByLabelText('Ask the assistant'),
      'open the film{Enter}'
    )
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ persona_id: 'p-doc' }))
  })

  it('asks with Auto-run once it is switched on, and remembers it', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    const running = turn({ status: 'processing', outcome: '', proposed_spec: null })
    const start = vi.spyOn(assistantApi, 'start').mockResolvedValue(running)
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(running))
    at('/p/p1')
    await userEvent.click(await screen.findByRole('checkbox', { name: /Auto-run/ }))
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'go ahead{Enter}')
    expect(start).toHaveBeenCalledWith(expect.objectContaining({ auto_run: true }))
    expect(localStorage.getItem('gvc-assistant-autorun')).toBe('1')
    useAssistantStore.getState().reset()
    expect(useAssistantStore.getState().autoRun).toBe(false)
  })

  it('has no picker when there are no personas', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    at('/p/p1')
    await screen.findByLabelText('Ask the assistant')
    expect(screen.queryByRole('combobox', { name: 'Persona' })).toBeNull()
  })

  it('drops a chosen persona the suite no longer offers', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    useAssistantStore.setState({ personaId: 'p-gone' })
    vi.spyOn(assistantApi, 'personas').mockResolvedValue([
      { id: 'p-doc', name: 'Documentarian', description: '', avatar: null },
    ])
    at('/p/p1')
    await screen.findByRole('combobox', { name: 'Persona' })
    // Sent again, it would end every turn with the suite's "persona not found".
    expect(useAssistantStore.getState().personaId).toBeNull()
  })

  it('works without a picker when the personas cannot be fetched', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    vi.spyOn(assistantApi, 'personas').mockRejectedValue(new Error('down'))
    at('/p/p1')
    await screen.findByLabelText('Ask the assistant')
    expect(screen.queryByRole('combobox', { name: 'Persona' })).toBeNull()
    expect(useAssistantStore.getState().error).toBeNull()
  })
})

const explainer: Recipe = {
  id: 'r1',
  name: 'Explainer',
  prompt: 'A 60-second explainer about {{topic}} on {{date}}',
  tags: ['short'],
  defaults: { aspect: '9:16' },
  inputs: ['topic'],
  sort_order: 0,
  created_at: '',
  updated_at: '',
}

describe('AssistantPanel recipes', () => {
  it('runs a recipe from the picker with its inputs and the local date', async () => {
    vi.mocked(recipesApi.list).mockResolvedValue([explainer])
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    const running = turn({ project_id: null, outcome: '', proposed_spec: null })
    const start = vi.spyOn(assistantApi, 'start').mockResolvedValue(running)
    vi.spyOn(assistantApi, 'session').mockResolvedValue(chat(running))
    at('/projects')

    await userEvent.click(await screen.findByRole('button', { name: 'Run a recipe' }))
    await userEvent.click(await screen.findByRole('button', { name: /Explainer/ }))
    const form = screen.getByRole('form', { name: 'Run Explainer' })
    expect(form).toHaveTextContent('A new video starts with 9:16')
    await userEvent.type(screen.getByLabelText('topic'), 'rivers')
    await userEvent.click(screen.getByRole('button', { name: /^Run$/ }))

    const sent = start.mock.calls[0][0]
    expect(sent).toMatchObject({
      prompt: '',
      recipe_id: 'r1',
      project_id: null,
      draft_spec: null,
    })
    expect(sent.recipe_inputs?.topic).toBe('rivers')
    expect(sent.recipe_inputs?.date).toBeTruthy()
    await waitFor(() => expect(useAssistantStore.getState().pendingRecipe).toBeNull())
  })

  it('on a project, says the defaults will not change the video', async () => {
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([])
    at('/p/p1')
    await screen.findByLabelText('Ask the assistant')
    useAssistantStore.getState().runRecipe(explainer)
    expect(
      await screen.findByText(/are for new videos and won't change this one/)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run on this video/ })).toBeInTheDocument()
  })

  it('shows a proposed edit to a recipe as a diff and saves it on its button', async () => {
    const proposal = {
      recipe_ref: 'rr1',
      op: 'update' as const,
      recipe_id: 'r1',
      before: {
        name: 'Explainer',
        prompt: 'Make {{topic}}\nKeep it short',
        tags: ['edu'],
        defaults: {},
        inputs: ['topic'],
      },
      after: {
        name: 'Explainer',
        prompt: 'Make {{topic}} in a {{tone}} tone\nKeep it short',
        tags: ['edu'],
        defaults: { aspect: '9:16' as const },
        inputs: ['topic', 'tone'],
      },
      fields: ['prompt' as const, 'defaults' as const],
      state: 'pending' as const,
    }
    const asked = turn({
      proposed_spec: null,
      changes: [],
      outcome: '',
      recipes: [proposal],
    })
    const saved = turn({ ...asked, recipes: [{ ...proposal, state: 'saved' }] })
    vi.spyOn(assistantApi, 'sessions').mockResolvedValue([chat(asked)])
    vi.spyOn(assistantApi, 'session')
      .mockResolvedValueOnce(chat(asked))
      .mockResolvedValue(chat(saved))
    const save = vi.spyOn(assistantApi, 'saveRecipe').mockResolvedValue(saved)
    at('/p/p1')

    const card = await screen.findByLabelText('Change recipe: Explainer')
    const diff = screen.getByLabelText('Prompt changes')
    expect(diff).toHaveTextContent('− Make {{topic}}')
    expect(diff).toHaveTextContent('+ Make {{topic}} in a {{tone}} tone')
    expect(diff).toHaveTextContent('Keep it short')
    expect(card).toHaveTextContent(/New videos start with: none → 9:16/)
    expect(screen.queryByRole('button', { name: 'Apply' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(save).toHaveBeenCalledWith('t1', 'rr1')
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument()
    // The list is read again, since the assistant's change came from outside it.
    expect(recipesApi.list).toHaveBeenCalled()
  })
})
