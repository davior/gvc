import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { recipesApi, type Recipe } from '@/api/recipes'
import { themesApi, type Theme } from '@/api/themes'
import { useAssistantStore } from '@/stores/assistant'
import { useRecipeStore } from '@/stores/recipes'
import RecipesView from '@/views/RecipesView'

const noir: Theme = {
  id: 'th1',
  name: 'Noir',
  prompt: 'Black and white',
  is_default: false,
  created_at: '',
  updated_at: '',
}

const teaser: Recipe = {
  id: 'r1',
  name: 'Teaser',
  prompt: 'A teaser for {{product}}',
  tags: ['promo'],
  defaults: {
    theme_id: 'th1',
    aspect: '9:16',
    voice: { voice: 'aura', provider: 'deepgram' },
  },
  inputs: ['product'],
  sort_order: 0,
  created_at: '',
  updated_at: '',
}

function show() {
  return render(
    <MemoryRouter>
      <RecipesView />
    </MemoryRouter>
  )
}

beforeEach(() => {
  useRecipeStore.getState().reset()
  useAssistantStore.getState().reset()
  vi.spyOn(themesApi, 'list').mockResolvedValue([noir])
})
afterEach(() => vi.restoreAllMocks())

describe('RecipesView', () => {
  it('lists recipes with what they ask for and start with, and runs one', async () => {
    vi.spyOn(recipesApi, 'list').mockResolvedValue([teaser])
    show()
    const row = (await screen.findByText('Teaser')).closest('li')!
    expect(row).toHaveTextContent('Asks for product')
    expect(row).toHaveTextContent('starts with Noir · 9:16 · voice aura, deepgram')
    await userEvent.click(screen.getByRole('button', { name: 'Run Teaser' }))
    expect(useAssistantStore.getState().pendingRecipe?.id).toBe('r1')
    expect(useAssistantStore.getState().open).toBe(true)
  })

  it('makes a recipe, listing the inputs found as the prompt is typed', async () => {
    vi.spyOn(recipesApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(recipesApi, 'create').mockResolvedValue(teaser)
    show()
    await userEvent.click(await screen.findByRole('button', { name: /New recipe/ }))
    await userEvent.type(screen.getByLabelText('Name'), 'Explainer')
    // userEvent reads braces as keys; doubled, they are typed as themselves.
    await userEvent.type(
      screen.getByLabelText('Prompt'),
      'About {{{{topic}} for {{{{ audience }}, on {{{{date}}'
    )
    expect(screen.getByText(/Asks for: topic, audience\./)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Tags'), 'Short, edu')
    await userEvent.selectOptions(screen.getByLabelText('Theme'), 'th1')
    await userEvent.selectOptions(screen.getByLabelText('Aspect'), '1:1')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(create).toHaveBeenCalledWith({
      name: 'Explainer',
      prompt: 'About {{topic}} for {{ audience }}, on {{date}}',
      tags: ['short', 'edu'],
      defaults: { theme_id: 'th1', aspect: '1:1', voice: null },
    })
  })

  it("keeps what the form doesn't show of a voice when editing", async () => {
    vi.spyOn(recipesApi, 'list').mockResolvedValue([teaser])
    const update = vi.spyOn(recipesApi, 'update').mockResolvedValue(teaser)
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Teaser' }))
    await userEvent.type(screen.getByLabelText('Voice speed'), '1.2')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(update.mock.calls[0][1].defaults?.voice).toEqual({
      voice: 'aura',
      provider: 'deepgram',
      speed: 1.2,
    })
  })

  it('imports a file exported from Gecko Notes', async () => {
    vi.spyOn(recipesApi, 'list').mockResolvedValue([])
    const importMany = vi
      .spyOn(recipesApi, 'importMany')
      .mockResolvedValue({ imported: 1, skipped: [], recipes: [] })
    show()
    const file = new File(
      [
        JSON.stringify([
          { name: 'Summarise', prompt: 'Summarise {{selected text}}', tags: ['ai'] },
          { name: '' },
        ]),
      ],
      'gecko-notes-recipes.json',
      { type: 'application/json' }
    )
    await userEvent.upload(screen.getByLabelText('Import recipes'), file)
    await waitFor(() =>
      expect(importMany).toHaveBeenCalledWith([
        { name: 'Summarise', prompt: 'Summarise {{selected text}}', tags: ['ai'] },
      ])
    )
    expect(await screen.findByText('Imported 1 recipe.')).toBeInTheDocument()
  })
})
