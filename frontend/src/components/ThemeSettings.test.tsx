import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import { themesApi, type Theme } from '@/api/themes'
import ThemePanel from '@/components/ThemePanel'
import ThemeSettings from '@/components/ThemeSettings'

function theme(overrides: Partial<Theme> = {}): Theme {
  return {
    id: 't-noir',
    name: 'Noir',
    prompt: 'Black and white, hard shadows',
    is_default: false,
    created_at: '2026-10-28T00:00:00',
    updated_at: '2026-10-28T00:00:00',
    ...overrides,
  }
}

const CLAY = theme({
  id: 't-clay',
  name: 'Claymation',
  prompt: 'Clay figures',
  is_default: true,
})

afterEach(() => {
  vi.restoreAllMocks()
})

let latest: VideoSpec
function Harness({ start }: { start: VideoSpec }) {
  const [spec, setSpec] = useState(start)
  latest = spec
  return (
    <MemoryRouter>
      <ThemeSettings spec={spec} onChange={setSpec} />
    </MemoryRouter>
  )
}

describe('ThemeSettings', () => {
  it('sets the theme in the spec, shows what it adds, and takes it out again', async () => {
    vi.spyOn(themesApi, 'list').mockResolvedValue([CLAY, theme()])
    render(<Harness start={{ title: 'T', style: { fit: 'crop' }, segments: [] }} />)
    expect(
      await screen.findByRole('option', { name: 'Claymation (default)' })
    ).toBeEnabled()

    fireEvent.change(screen.getByLabelText('Theme for this video'), {
      target: { value: 't-noir' },
    })
    expect(latest.style).toEqual({ fit: 'crop', theme: 't-noir' })
    expect(screen.getByText(/Black and white, hard shadows/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Theme for this video'), {
      target: { value: '' },
    })
    expect(latest.style).toEqual({ fit: 'crop' })
  })

  it('says so when the theme named no longer exists', async () => {
    vi.spyOn(themesApi, 'list').mockResolvedValue([CLAY])
    render(<Harness start={{ title: 'T', style: { theme: 'gone' }, segments: [] }} />)
    expect(
      await screen.findByRole('option', { name: 'A theme that no longer exists' })
    ).toBeInTheDocument()
    expect(screen.getByText(/Generating ignores it/)).toBeInTheDocument()
  })

  it('reads the list again for a theme it has not seen, such as one the assistant made', async () => {
    const list = vi
      .spyOn(themesApi, 'list')
      .mockResolvedValueOnce([CLAY])
      .mockResolvedValueOnce([CLAY, theme({ id: 't-new', name: 'Ink wash' })])
    render(<Harness start={{ title: 'T', style: { theme: 't-new' }, segments: [] }} />)
    expect(await screen.findByRole('option', { name: 'Ink wash' })).toBeInTheDocument()
    expect(screen.getByLabelText('Theme for this video')).toHaveValue('t-new')
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('points to Settings when there are none', async () => {
    vi.spyOn(themesApi, 'list').mockResolvedValue([])
    render(<Harness start={{ title: 'T', segments: [] }} />)
    expect(
      await screen.findByRole('link', { name: /make one in settings/i })
    ).toHaveAttribute('href', '/settings')
  })
})

describe('ThemePanel', () => {
  it('makes the first theme the default, and lets the default be moved', async () => {
    const list = vi.spyOn(themesApi, 'list').mockResolvedValue([])
    const create = vi.spyOn(themesApi, 'create').mockResolvedValue(theme())
    render(<ThemePanel />)

    await userEvent.click(await screen.findByRole('button', { name: /add a theme/i }))
    await userEvent.type(screen.getByLabelText('Name'), 'Noir')
    await userEvent.type(screen.getByLabelText('Added to every prompt'), ' Hard shadows ')
    list.mockResolvedValue([theme({ is_default: true }), { ...CLAY, is_default: false }])
    await userEvent.click(screen.getByRole('button', { name: 'Save theme' }))
    expect(create).toHaveBeenCalledWith({
      name: 'Noir',
      prompt: 'Hard shadows',
      is_default: true,
    })

    const update = vi.spyOn(themesApi, 'update').mockResolvedValue(CLAY)
    await waitFor(() => expect(screen.getAllByText('Default')).toHaveLength(1))
    await userEvent.click(screen.getByRole('button', { name: 'Make default' }))
    expect(update).toHaveBeenCalledWith('t-clay', { is_default: true })
  })
})
