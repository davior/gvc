import { create } from 'zustand'
import { apiErrorMessage } from '@/api/client'
import {
  projectsApi,
  specIssuesOf,
  type Project,
  type ProjectSummary,
  type SpecIssue,
  type Version,
  type VideoSpec,
} from '@/api/projects'

/**
 * The project list and the one project open in the editor.
 *
 * The editor's working copy (`draft`) lives here, not in the view, so the scene list
 * and the JSON tab edit the same document and a tab switch loses nothing. `project`
 * is what the server last confirmed; `dirty` is whether the two differ.
 *
 * Every await is followed by a staleness check: opening project B while A is still
 * loading must not let A's late answer land on B's screen.
 */

interface ProjectState {
  list: ProjectSummary[]
  listLoading: boolean
  listError: string | null

  project: Project | null
  draft: VideoSpec | null
  dirty: boolean
  loading: boolean
  saving: boolean
  error: string | null
  /** Problems the server found with the last save, by path. */
  issues: SpecIssue[]

  versions: Version[]

  loadList: () => Promise<void>
  createBlank: (title: string) => Promise<Project | null>
  open: (id: string) => Promise<void>
  edit: (next: VideoSpec) => void
  discard: () => void
  save: (message?: string) => Promise<boolean>
  loadVersions: () => Promise<void>
  revert: (versionId: string) => Promise<void>
  remove: (id: string) => Promise<boolean>
  reset: () => void
}

const initial = {
  list: [],
  listLoading: false,
  listError: null,
  project: null,
  draft: null,
  dirty: false,
  loading: false,
  saving: false,
  error: null,
  issues: [],
  versions: [],
}

// Bumped by every request that replaces what is on screen, and by `reset()`. A
// response whose token is no longer current is dropped.
let listToken = 0
let projectToken = 0

export const useProjectStore = create<ProjectState>((set, get) => ({
  ...initial,

  async loadList() {
    const token = ++listToken
    set({ listLoading: true, listError: null })
    try {
      const page = await projectsApi.list()
      if (token !== listToken) return
      set({ list: page.data, listLoading: false })
    } catch (error) {
      if (token !== listToken) return
      set({ listLoading: false, listError: apiErrorMessage(error) })
    }
  },

  async createBlank(title) {
    const token = listToken
    try {
      const project = await projectsApi.create(title)
      if (token === listToken) set({ list: [project, ...get().list] })
      return project
    } catch (error) {
      if (token === listToken) set({ listError: apiErrorMessage(error) })
      return null
    }
  },

  async open(id) {
    const token = ++projectToken
    set({
      loading: true,
      error: null,
      issues: [],
      versions: [],
      project: null,
      draft: null,
    })
    try {
      const project = await projectsApi.get(id)
      if (token !== projectToken) return
      set({ project, draft: project.spec, dirty: false, loading: false })
    } catch (error) {
      if (token !== projectToken) return
      set({ loading: false, error: apiErrorMessage(error) })
    }
  },

  edit(next) {
    set({ draft: next, dirty: true })
  },

  discard() {
    const project = get().project
    if (project) set({ draft: project.spec, dirty: false, issues: [] })
  },

  async save(message = '') {
    const { project, draft } = get()
    if (!project || !draft) return false
    const token = projectToken
    set({ saving: true, error: null, issues: [] })
    try {
      const saved = await projectsApi.save(project.id, draft, message)
      if (token !== projectToken) return false
      // The server's copy, not the draft: it fills in defaults and migrates, and the
      // editor should show the document as it is now stored.
      set({ project: saved, draft: saved.spec, dirty: false, saving: false })
      void get().loadVersions()
      return true
    } catch (error) {
      if (token !== projectToken) return false
      set({ saving: false, error: apiErrorMessage(error), issues: specIssuesOf(error) })
      return false
    }
  },

  async loadVersions() {
    const project = get().project
    if (!project) return
    const token = projectToken
    try {
      const page = await projectsApi.versions(project.id)
      if (token !== projectToken) return
      set({ versions: page.data })
    } catch (error) {
      if (token !== projectToken) return
      set({ error: apiErrorMessage(error) })
    }
  },

  async revert(versionId) {
    const project = get().project
    if (!project) return
    const token = projectToken
    set({ saving: true, error: null })
    try {
      const reverted = await projectsApi.revert(project.id, versionId)
      if (token !== projectToken) return
      set({
        project: reverted,
        draft: reverted.spec,
        dirty: false,
        saving: false,
        issues: [],
      })
      void get().loadVersions()
    } catch (error) {
      if (token !== projectToken) return
      set({ saving: false, error: apiErrorMessage(error) })
    }
  },

  async remove(id) {
    try {
      await projectsApi.remove(id)
      set({ list: get().list.filter((p) => p.id !== id) })
      return true
    } catch (error) {
      set({ listError: apiErrorMessage(error) })
      return false
    }
  },

  reset() {
    listToken += 1
    projectToken += 1
    set({ ...initial })
  },
}))
