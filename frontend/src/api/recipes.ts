import client from '@/api/client'
import type { Aspect } from '@/api/projects'

/**
 * Recipes: saved requests with `{{inputs}}`, run through the assistant to make a video
 * or change the open one. Gecko Notes' recipes, with the settings a new video starts with.
 *
 * Running one is not here: it is an assistant turn (`assistantApi.start` with
 * `recipe_id`), so it is followed, stopped and applied like every other request.
 */

interface DataResponse<T> {
  data: T
}

interface ListResponse<T> {
  data: T[]
  total: number
}

/** A partial voice: what a recipe pins, the rest left to the video. */
export interface RecipeVoice {
  provider?: 'auto' | 'deepgram' | 'fal' | null
  voice?: string | null
  speed?: number | null
  expressivity?: number | null
}

/** What a video made from the recipe starts with. Never applied to an open video. */
export interface RecipeDefaults {
  theme_id?: string | null
  aspect?: Aspect | null
  voice?: RecipeVoice | null
}

export interface Recipe {
  id: string
  name: string
  prompt: string
  tags: string[]
  defaults: RecipeDefaults
  /** The placeholders a run asks for: every one but the built-ins. */
  inputs: string[]
  sort_order: number
  created_at: string
  updated_at: string
}

export interface RecipeInput {
  name: string
  prompt: string
  tags?: string[]
  defaults?: RecipeDefaults
}

/** One entry of an exported file. Gecko Notes' export (`[{name, prompt, tags}]`) is one. */
export interface RecipeExport {
  name: string
  prompt: string
  tags: string[]
  defaults?: RecipeDefaults
}

export interface RecipeImportResult {
  imported: number
  skipped: string[]
  recipes: Recipe[]
}

export const MAX_RECIPE_PROMPT = 10_000

export const recipesApi = {
  list(): Promise<Recipe[]> {
    return client.get<ListResponse<Recipe>>('/recipes').then((r) => r.data.data)
  },

  create(input: RecipeInput): Promise<Recipe> {
    return client.post<DataResponse<Recipe>>('/recipes', input).then((r) => r.data.data)
  },

  update(id: string, changes: Partial<RecipeInput>): Promise<Recipe> {
    return client
      .put<DataResponse<Recipe>>(`/recipes/${id}`, changes)
      .then((r) => r.data.data)
  },

  remove(id: string): Promise<void> {
    return client.delete(`/recipes/${id}`).then(() => undefined)
  },

  importMany(recipes: RecipeExport[]): Promise<RecipeImportResult> {
    return client
      .post<DataResponse<RecipeImportResult>>('/recipes/import', { recipes })
      .then((r) => r.data.data)
  },
}
