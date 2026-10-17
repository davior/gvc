import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { generationsApi, type GenerationModel } from '@/api/generations'
import { gamApi } from '@/api/gam'
import { projectsApi, type Project } from '@/api/projects'
import GenerateDialog from '@/components/GenerateDialog'
import { useGenerationStore } from '@/stores/generations'
import { useProjectStore } from '@/stores/projects'

const MODELS: GenerationModel[] = [
  {
    id: 'm-flux',
    kind: 'text_to_image',
    label: 'FLUX',
    note: '',
    price: '$0.003 a megapixel',
    unit_price: 0.003,
    price_unit: 'megapixel',
    options: { image_sizes: ['landscape_16_9'], max_outputs: 4 },
  },
  {
    id: 'm-edit',
    kind: 'text_to_image',
    label: 'Nano',
    note: '',
    price: '$0.039 an image',
    unit_price: 0.039,
    price_unit: 'image',
    options: { aspect_ratios: ['16:9'], max_outputs: 4 },
  },
  {
    id: 'm-veo',
    kind: 'image_to_video',
    label: 'Veo',
    note: '',
    price: '$0.10 a second',
    unit_price: 0.1,
    price_unit: 'second',
    options: { durations: ['4s', '8s'] },
  },
]

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
    assets: {
      a_map: { from: 'gam', id: 'p1', type: 'image', label: 'Valley map' },
      a_dam: { from: 'generate', type: 'image', prompt: 'A dam' },
      a_flood: { from: 'generate', type: 'video', prompt: 'Water rising' },
    },
    segments: [],
  },
}

beforeEach(async () => {
  useProjectStore.getState().reset()
  useGenerationStore.getState().reset()
  vi.spyOn(projectsApi, 'get').mockResolvedValue(project)
  vi.spyOn(gamApi, 'lookup').mockResolvedValue({})
  vi.spyOn(generationsApi, 'list').mockResolvedValue([])
  vi.spyOn(generationsApi, 'models').mockResolvedValue(MODELS)
  await useProjectStore.getState().open('p')
  await useGenerationStore.getState().load('p')
})
afterEach(() => vi.restoreAllMocks())

describe('GenerateDialog', () => {
  it('prices the run and sends the edited prompt with the draft', async () => {
    const start = vi.spyOn(generationsApi, 'start').mockResolvedValue({} as never)
    const onClose = vi.fn()
    render(<GenerateDialog assetKey="a_dam" onClose={onClose} />)
    await screen.findByRole('option', { name: /Nano/ })
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Model' }),
      'm-edit'
    )
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Pictures' }), '3')
    expect(screen.getByText(/About \$0\.12/)).toBeInTheDocument()
    const prompt = screen.getByRole('textbox')
    await userEvent.clear(prompt)
    await userEvent.type(prompt, 'A dam at dusk')
    await userEvent.click(screen.getByRole('button', { name: /Generate/ }))

    const [, body] = start.mock.calls[0]
    expect(body).toMatchObject({
      asset_key: 'a_dam',
      prompt: 'A dam at dusk',
      model_id: 'm-edit',
      outputs: 3,
    })
    expect(body.draft_spec?.assets?.a_dam).toMatchObject({ prompt: 'A dam at dusk' })
    expect(useProjectStore.getState().draft?.assets?.a_dam).toMatchObject({
      prompt: 'A dam at dusk',
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('makes a clip from a picture in the video, for a length the model offers', async () => {
    const start = vi.spyOn(generationsApi, 'start').mockResolvedValue({} as never)
    render(<GenerateDialog assetKey="a_flood" onClose={vi.fn()} />)
    await screen.findByRole('option', { name: /Veo/ })
    expect(screen.getByRole('combobox', { name: 'Made from' })).toHaveValue('p1')
    expect(screen.queryByRole('combobox', { name: 'Pictures' })).toBeNull()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Length' }), '8s')
    expect(screen.getByText(/About \$0\.80/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Generate/ }))
    expect(start.mock.calls[0][1]).toMatchObject({
      model_id: 'm-veo',
      duration: '8',
      base_gam_ids: ['p1'],
    })
  })

  it('says why it could not start, and stays open', async () => {
    vi.spyOn(generationsApi, 'start').mockRejectedValue(new Error('no key'))
    const onClose = vi.fn()
    render(<GenerateDialog assetKey="a_dam" onClose={onClose} />)
    await screen.findByRole('option', { name: /FLUX/ })
    expect(
      screen.getByText(/\$0\.003 a megapixel, on your fal\.ai account/)
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Generate/ }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
