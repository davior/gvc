import { create } from 'zustand'
import { apiErrorMessage } from '@/api/client'
import {
  recipesApi,
  type Recipe,
  type RecipeExport,
  type RecipeImportResult,
  type RecipeInput,
} from '@/api/recipes'

/**
 * The recipe list, shared by the Recipes page and the assistant's picker. Reloaded after
 * the assistant's proposal is saved, since that changes the list from outside this store.
 */

interface RecipesState {
  recipes: Recipe[]
  loaded: boolean
  error: string | null
  load: () => Promise<void>
  create: (input: RecipeInput) => Promise<Recipe | null>
  update: (id: string, changes: Partial<RecipeInput>) => Promise<Recipe | null>
  remove: (id: string) => Promise<boolean>
  importMany: (items: RecipeExport[]) => Promise<RecipeImportResult | null>
  reset: () => void
}

let token = 0

export const useRecipeStore = create<RecipesState>((set, get) => {
  async function act<T>(work: () => Promise<T>, fallback: string): Promise<T | null> {
    const mine = token
    set({ error: null })
    try {
      const result = await work()
      if (mine !== token) return null
      await get().load()
      return result
    } catch (error) {
      if (mine === token) set({ error: apiErrorMessage(error, fallback) })
      return null
    }
  }

  return {
    recipes: [],
    loaded: false,
    error: null,

    async load() {
      const mine = ++token
      try {
        const recipes = await recipesApi.list()
        if (mine !== token) return
        set({ recipes, loaded: true })
      } catch (error) {
        if (mine !== token) return
        set({ error: apiErrorMessage(error, 'Could not load recipes'), loaded: true })
      }
    },

    create: (input) => act(() => recipesApi.create(input), 'Could not save the recipe'),
    update: (id, changes) =>
      act(() => recipesApi.update(id, changes), 'Could not save the recipe'),
    remove: async (id) =>
      (await act(() => recipesApi.remove(id).then(() => true), 'Could not delete it')) ??
      false,
    importMany: (items) =>
      act(() => recipesApi.importMany(items), 'Could not import the recipes'),

    reset() {
      token += 1
      set({ recipes: [], loaded: false, error: null })
    },
  }
})
