import { create } from 'zustand'
import { apiErrorMessage } from '@/api/client'
import { ACTIVE, rendersApi, type Estimate, type Render } from '@/api/renders'

/**
 * The renders of the project open in the editor, and the one in progress.
 *
 * A running render is polled every couple of seconds until it finishes. The poll is
 * one timer, re-armed only after the previous answer arrives, and every answer is
 * checked against a token so a project closed mid-render cannot have its render's
 * progress land on the next one.
 */

const POLL_MS = 2000

interface RenderState {
  projectId: string | null
  renders: Render[]
  estimate: Estimate | null
  starting: boolean
  /** The render being saved to GAM, if one is. */
  saving: string | null
  error: string | null

  load: (projectId: string) => Promise<void>
  refreshEstimate: () => Promise<void>
  start: (preview: boolean) => Promise<void>
  cancel: (id: string) => Promise<void>
  remove: (id: string) => Promise<void>
  saveToGam: (id: string) => Promise<void>
  reset: () => void
}

let token = 0
let timer: ReturnType<typeof setTimeout> | null = null

function stopPolling() {
  if (timer) clearTimeout(timer)
  timer = null
}

export const useRenderStore = create<RenderState>((set, get) => {
  const replace = (render: Render) =>
    set({ renders: get().renders.map((r) => (r.id === render.id ? render : r)) })

  function poll(mine: number) {
    stopPolling()
    const active = get().renders.find((r) => ACTIVE.includes(r.status))
    if (!active) return
    timer = setTimeout(async () => {
      try {
        const fresh = await rendersApi.get(active.id)
        if (mine !== token) return
        replace(fresh)
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
      poll(mine)
    }, POLL_MS)
  }

  return {
    projectId: null,
    renders: [],
    estimate: null,
    starting: false,
    saving: null,
    error: null,

    async load(projectId) {
      const mine = ++token
      stopPolling()
      set({ projectId, renders: [], estimate: null, error: null })
      try {
        const [renders, estimate] = await Promise.all([
          rendersApi.list(projectId),
          rendersApi.estimate(projectId),
        ])
        if (mine !== token) return
        set({ renders, estimate })
        poll(mine)
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error) })
      }
    },

    async refreshEstimate() {
      const projectId = get().projectId
      if (!projectId) return
      const mine = token
      try {
        const estimate = await rendersApi.estimate(projectId)
        if (mine === token) set({ estimate })
      } catch {
        /* the next load says what is wrong */
      }
    },

    async start(preview) {
      const projectId = get().projectId
      if (!projectId) return
      const mine = token
      set({ starting: true, error: null })
      try {
        const render = await rendersApi.start(projectId, preview)
        if (mine !== token) return
        set({ renders: [render, ...get().renders], starting: false })
        poll(mine)
      } catch (error) {
        if (mine !== token) return
        set({ starting: false, error: apiErrorMessage(error) })
      }
    },

    async cancel(id) {
      const mine = token
      try {
        const render = await rendersApi.cancel(id)
        if (mine === token) replace(render)
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async remove(id) {
      const mine = token
      try {
        await rendersApi.remove(id)
        if (mine === token) set({ renders: get().renders.filter((r) => r.id !== id) })
      } catch (error) {
        if (mine === token) set({ error: apiErrorMessage(error) })
      }
    },

    async saveToGam(id) {
      const mine = token
      set({ saving: id, error: null })
      try {
        const render = await rendersApi.saveToGam(id)
        if (mine !== token) return
        replace(render)
        set({ saving: null })
      } catch (error) {
        if (mine !== token) return
        set({ saving: null, error: apiErrorMessage(error) })
      }
    },

    reset() {
      token += 1
      stopPolling()
      set({
        projectId: null,
        renders: [],
        estimate: null,
        starting: false,
        saving: null,
        error: null,
      })
    },
  }
})
