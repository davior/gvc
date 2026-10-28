import client from '@/api/client'

/**
 * Named looks for what gets generated. A project names one in `style.theme`, and its
 * prompt is added to every picture and clip prompt generated for that project.
 *
 * Not the light/dark switch, which is `stores/theme.ts`.
 */

interface DataResponse<T> {
  data: T
}

interface ListResponse<T> {
  data: T[]
  total: number
}

export interface Theme {
  id: string
  name: string
  /** Added after each generation prompt, on its own paragraph. */
  prompt: string
  /** The theme a new project starts with; at most one is. */
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface ThemeInput {
  name: string
  prompt: string
  is_default?: boolean
}

/** The server's cap; GAM takes 4000 characters for a prompt and its theme together. */
export const MAX_THEME_PROMPT = 1500

export const themesApi = {
  list(): Promise<Theme[]> {
    return client.get<ListResponse<Theme>>('/themes').then((r) => r.data.data)
  },

  create(input: ThemeInput): Promise<Theme> {
    return client.post<DataResponse<Theme>>('/themes', input).then((r) => r.data.data)
  },

  update(id: string, changes: Partial<ThemeInput>): Promise<Theme> {
    return client
      .put<DataResponse<Theme>>(`/themes/${id}`, changes)
      .then((r) => r.data.data)
  },

  remove(id: string): Promise<void> {
    return client.delete(`/themes/${id}`).then(() => undefined)
  },
}
