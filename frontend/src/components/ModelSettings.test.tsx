import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { generationsApi, type GenerationModel } from '@/api/generations'
import type { VideoSpec } from '@/api/projects'
import ModelSettings from '@/components/ModelSettings'
import { useGenerationStore } from '@/stores/generations'

const model = (over: Partial<GenerationModel>): GenerationModel => ({
  id: 'm',
  endpoint_id: 'fal-ai/m',
  is_default: false,
  kind: 'text_to_image',
  label: 'M',
  note: '',
  price: '$0.06 a image',
  unit_price: 0.06,
  price_unit: 'image',
  options: {},
  ...over,
})

const SCHNELL = model({
  id: 'm-schnell',
  endpoint_id: 'fal-ai/flux/schnell',
  label: 'Schnell',
})
const ULTRA = model({
  id: 'm-ultra',
  endpoint_id: 'fal-ai/flux-pro/v1.1-ultra',
  label: 'Ultra',
  is_default: true,
})

const spec: VideoSpec = { title: 'T', assets: {}, segments: [] }

beforeEach(() => {
  useGenerationStore.getState().reset()
  vi.spyOn(generationsApi, 'models').mockResolvedValue([ULTRA, SCHNELL])
})
afterEach(() => vi.restoreAllMocks())

describe('ModelSettings', () => {
  it('names the library default and writes a choice into the spec by endpoint', async () => {
    const onChange = vi.fn()
    render(<ModelSettings spec={spec} onChange={onChange} />)
    const select = screen.getByRole('combobox', { name: 'Model for pictures' })
    expect(
      await screen.findByRole('option', { name: 'Library default (Ultra)' })
    ).toBeInTheDocument()

    await userEvent.selectOptions(select, 'fal-ai/flux/schnell')

    expect(onChange.mock.calls[0][0].style).toEqual({
      models: { text_to_image: 'fal-ai/flux/schnell' },
    })
  })

  it('clears a kind back to the default, and the block with its last kind', async () => {
    const onChange = vi.fn()
    const chosen = {
      ...spec,
      style: { models: { text_to_image: 'fal-ai/flux/schnell' } },
    }
    render(<ModelSettings spec={chosen} onChange={onChange} />)
    await screen.findByRole('option', { name: /Schnell/ })

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Model for pictures' }),
      ''
    )

    expect(onChange.mock.calls[0][0].style?.models).toBeUndefined()
  })

  it('says so when the project names a model the library does not offer', async () => {
    const gone = { ...spec, style: { models: { text_to_image: 'fal-ai/flux-pro/v1' } } }
    render(<ModelSettings spec={gone} onChange={vi.fn()} />)
    expect(
      await screen.findByRole('option', {
        name: 'fal-ai/flux-pro/v1 (not in the library)',
      })
    ).toBeInTheDocument()
  })
})
