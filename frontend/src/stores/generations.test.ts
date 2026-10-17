import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { generationsApi, type Generation } from '@/api/generations'
import { projectsApi, type Project } from '@/api/projects'
import { gamApi } from '@/api/gam'
import { useGenerationStore } from '@/stores/generations'
import { useProjectStore } from '@/stores/projects'

const project: Project = {
  id: 'p',
  title: 'T',
  origin: 'blank',
  version: 1,
  created_at: '2026-10-16T00:00:00',
  updated_at: '2026-10-16T00:00:00',
  pending_note_media: 0,
  spec: {
    title: 'T',
    assets: { a_dam: { from: 'generate', type: 'image', prompt: 'A dam' } },
    segments: [],
  },
}

function generation(overrides: Partial<Generation> = {}): Generation {
  return {
    id: 'g',
    project_id: 'p',
    asset_key: 'a_dam',
    kind: 'text_to_image',
    prompt: 'A dam',
    model_label: 'FLUX.1 [schnell]',
    status: 'done',
    stage: '',
    progress: 100,
    detail: '',
    error: null,
    result_ids: ['x1', 'x2'],
    used_id: null,
    estimate: 0.006,
    created_at: '2026-10-16T00:00:00',
    updated_at: '2026-10-16T00:00:00',
    ...overrides,
  }
}

beforeEach(async () => {
  useProjectStore.getState().reset()
  useGenerationStore.getState().reset()
  vi.spyOn(projectsApi, 'get').mockResolvedValue(project)
  vi.spyOn(gamApi, 'lookup').mockResolvedValue({})
  await useProjectStore.getState().open('p')
})
afterEach(() => vi.restoreAllMocks())

describe('generation store', () => {
  it('puts a finished picture into the draft once and records it', async () => {
    vi.spyOn(generationsApi, 'list')
      .mockResolvedValueOnce([generation()])
      .mockResolvedValue([generation({ used_id: 'x1' })])
    const use = vi
      .spyOn(generationsApi, 'use')
      .mockResolvedValue(generation({ used_id: 'x1' }))
    await useGenerationStore.getState().load('p')

    const projects = useProjectStore.getState()
    expect(projects.dirty).toBe(true)
    expect(projects.draft?.assets?.a_dam).toMatchObject({
      status: 'ready',
      result: { from: 'gam', id: 'x1' },
    })
    expect(use).toHaveBeenCalledWith('g', 'x1')

    // Discarded, it stays out: the row says it was used.
    projects.discard()
    await useGenerationStore.getState().load('p')
    expect(use).toHaveBeenCalledTimes(1)
  })

  it('switches to another output', async () => {
    vi.spyOn(generationsApi, 'list').mockResolvedValue([generation({ used_id: 'x1' })])
    const use = vi
      .spyOn(generationsApi, 'use')
      .mockResolvedValue(generation({ used_id: 'x2' }))
    await useGenerationStore.getState().load('p')
    await useGenerationStore.getState().choose('g', 'x2')
    expect(use).toHaveBeenCalledWith('g', 'x2')
    expect(useProjectStore.getState().draft?.assets?.a_dam).toMatchObject({
      result: { id: 'x2' },
    })
  })

  it('follows a running one until it is done', async () => {
    vi.useFakeTimers()
    try {
      const list = vi
        .spyOn(generationsApi, 'list')
        .mockResolvedValueOnce([generation({ status: 'processing', result_ids: [] })])
        .mockResolvedValue([generation()])
      vi.spyOn(generationsApi, 'use').mockResolvedValue(generation({ used_id: 'x1' }))
      await useGenerationStore.getState().load('p')
      expect(useProjectStore.getState().dirty).toBe(false)
      await vi.advanceTimersByTimeAsync(3000)
      expect(list).toHaveBeenCalledTimes(2)
      expect(useProjectStore.getState().draft?.assets?.a_dam).toMatchObject({
        status: 'ready',
      })
      // Nothing left running: no more asking.
      await vi.advanceTimersByTimeAsync(10000)
      expect(list).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('leaves another project alone', async () => {
    vi.spyOn(generationsApi, 'list').mockResolvedValue([generation({ project_id: 'q' })])
    const use = vi.spyOn(generationsApi, 'use')
    await useGenerationStore.getState().load('q')
    expect(useProjectStore.getState().dirty).toBe(false)
    expect(use).not.toHaveBeenCalled()
  })
})
