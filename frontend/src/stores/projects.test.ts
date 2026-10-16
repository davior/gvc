import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { projectsApi, type Project } from '@/api/projects'
import { useProjectStore } from '@/stores/projects'

function project(id: string, title = id): Project {
  return {
    id,
    title,
    origin: 'blank',
    version: 1,
    created_at: '2026-10-16T00:00:00',
    updated_at: '2026-10-16T00:00:00',
    pending_note_media: 0,
    spec: { id, title, segments: [] },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

beforeEach(() => useProjectStore.getState().reset())
afterEach(() => vi.restoreAllMocks())

describe('project store', () => {
  it('drops a late answer for a project that is no longer open', async () => {
    const a = deferred<Project>()
    vi.spyOn(projectsApi, 'get').mockImplementation((id) =>
      id === 'a' ? a.promise : Promise.resolve(project('b'))
    )
    const store = useProjectStore.getState()
    const openingA = store.open('a')
    await store.open('b')
    a.resolve(project('a'))
    await openingA
    expect(useProjectStore.getState().project?.id).toBe('b')
  })

  it('edits a draft, then takes the server copy as the new baseline on save', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project('p', 'Old'))
    const saved = { ...project('p', 'New'), version: 2 }
    vi.spyOn(projectsApi, 'save').mockResolvedValue(saved)
    vi.spyOn(projectsApi, 'versions').mockResolvedValue({
      data: [],
      total: 0,
      limit: 50,
      offset: 0,
    })
    const store = useProjectStore.getState()
    await store.open('p')

    store.edit({ ...useProjectStore.getState().draft!, title: 'New' })
    expect(useProjectStore.getState().dirty).toBe(true)

    expect(await store.save()).toBe(true)
    const state = useProjectStore.getState()
    expect(state.dirty).toBe(false)
    expect(state.project?.version).toBe(2)
    expect(state.draft).toEqual(saved.spec)
  })

  it('keeps the draft and shows the issues when the server refuses it', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project('p'))
    const refusal = new AxiosError('invalid')
    const issues = [{ path: ['voice', 'speed'], message: 'too fast' }]
    refusal.response = {
      data: {
        detail: { code: 'invalid_spec', message: 'The spec has 1 problem', issues },
      },
      status: 422,
      statusText: '',
      headers: {},
      config: {} as never,
    }
    vi.spyOn(projectsApi, 'save').mockRejectedValue(refusal)
    const store = useProjectStore.getState()
    await store.open('p')
    const draft = { ...useProjectStore.getState().draft!, title: 'Edited' }
    store.edit(draft)

    expect(await store.save()).toBe(false)
    const state = useProjectStore.getState()
    expect(state.issues).toEqual(issues)
    expect(state.draft).toEqual(draft)
    expect(state.dirty).toBe(true)
  })

  it('forgets everything on reset', async () => {
    vi.spyOn(projectsApi, 'get').mockResolvedValue(project('p'))
    await useProjectStore.getState().open('p')
    useProjectStore.getState().reset()
    expect(useProjectStore.getState().project).toBeNull()
    expect(useProjectStore.getState().draft).toBeNull()
  })
})
