import { create } from 'zustand'
import { apiErrorMessage } from '@/api/client'
import {
  generationsApi,
  RUNNING,
  type Generation,
  type GenerationModel,
  type GenerationStart,
} from '@/api/generations'
import { fillGenerated } from '@/spec/generation'
import { useProjectStore } from '@/stores/projects'

/**
 * The generations of the project open in the editor.
 *
 * Polled every few seconds while any runs: each read of the list is also what makes
 * GVC catch up with GAM, so the poll is the only thing following them. A finished one
 * whose output isn't in the video yet is put into the editor's draft, and that choice
 * recorded, so it lands once: after that, Discard drops it like any other edit, and
 * the placeholder offers the outputs again.
 */

const POLL_MS = 3000

interface GenerationState {
  projectId: string | null
  rows: Generation[]
  models: GenerationModel[] | null
  starting: boolean
  error: string | null

  load: (projectId: string) => Promise<void>
  loadModels: () => Promise<void>
  start: (body: GenerationStart) => Promise<boolean>
  cancel: (id: string) => Promise<void>
  /** Put this output in the video in place of the one there. */
  choose: (id: string, assetId: string) => Promise<void>
  reset: () => void
}

let token = 0
let timer: ReturnType<typeof setTimeout> | null = null

function stopPolling() {
  if (timer) clearTimeout(timer)
  timer = null
}

export const useGenerationStore = create<GenerationState>((set, get) => {
  const replace = (row: Generation) =>
    set({ rows: get().rows.map((r) => (r.id === row.id ? row : r)) })

  /** Into the draft, if it is still this project's and still has the placeholder. */
  function putInDraft(row: Generation, assetId: string): boolean {
    const projects = useProjectStore.getState()
    const draft = projects.draft
    if (!draft || projects.project?.id !== get().projectId) return false
    if (draft.assets?.[row.asset_key]?.from !== 'generate') return false
    projects.edit(fillGenerated(draft, row.asset_key, assetId))
    return true
  }

  async function settle(mine: number) {
    const fresh = get().rows.filter(
      (r) => r.status === 'done' && r.result_ids.length > 0 && !r.used_id
    )
    if (fresh.length === 0) return
    void useProjectStore.getState().loadGamAssets(fresh.flatMap((r) => r.result_ids))
    for (const row of fresh) {
      if (!putInDraft(row, row.result_ids[0])) continue
      try {
        const used = await generationsApi.use(row.id, row.result_ids[0])
        if (mine !== token) return
        replace(used)
      } catch {
        /* recorded next time; the draft already has it */
      }
    }
  }

  function poll(mine: number) {
    stopPolling()
    if (!get().rows.some((r) => RUNNING.includes(r.status))) return
    timer = setTimeout(async () => {
      const projectId = get().projectId
      if (!projectId) return
      try {
        const rows = await generationsApi.list(projectId)
        if (mine !== token) return
        set({ rows })
        await settle(mine)
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
      if (mine === token) poll(mine)
    }, POLL_MS)
  }

  return {
    projectId: null,
    rows: [],
    models: null,
    starting: false,
    error: null,

    async load(projectId) {
      const mine = ++token
      stopPolling()
      set({ projectId, rows: [], error: null })
      try {
        const rows = await generationsApi.list(projectId)
        if (mine !== token) return
        set({ rows })
        // Old outputs need their pictures for the alternatives, not only new ones.
        const made = rows.flatMap((r) => r.result_ids)
        if (made.length) void useProjectStore.getState().loadGamAssets(made)
        await settle(mine)
        poll(mine)
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
    },

    async loadModels() {
      if (get().models) return
      const mine = token
      try {
        const models = await generationsApi.models()
        if (mine === token) set({ models })
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async start(body) {
      const projectId = get().projectId
      if (!projectId) return false
      const mine = token
      set({ starting: true, error: null })
      try {
        const row = await generationsApi.start(projectId, body)
        if (mine !== token) return false
        set({ rows: [...get().rows, row], starting: false })
        poll(mine)
        return true
      } catch (error) {
        if (mine !== token) return false
        set({ starting: false, error: apiErrorMessage(error) })
        return false
      }
    },

    async cancel(id) {
      const mine = token
      try {
        const row = await generationsApi.cancel(id)
        if (mine === token) replace(row)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async choose(id, assetId) {
      const row = get().rows.find((r) => r.id === id)
      if (!row || !putInDraft(row, assetId)) return
      const mine = token
      try {
        const used = await generationsApi.use(id, assetId)
        if (mine === token) replace(used)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    reset() {
      token += 1
      stopPolling()
      set({ projectId: null, rows: [], models: null, starting: false, error: null })
    },
  }
})
