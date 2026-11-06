import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { gamApi } from '@/api/gam'
import { projectsApi, type Project } from '@/api/projects'
import PlaylistStart from '@/components/PlaylistStart'
import { useProjectStore } from '@/stores/projects'

function show() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<PlaylistStart />} />
        <Route path="/p/:id" element={<p>Opened project</p>} />
      </Routes>
    </MemoryRouter>
  )
}

const playlist = {
  id: 'p1',
  name: 'The financial crisis',
  description: null,
  item_count: 5,
  total_seconds: 120,
  thumb_url: null,
  updated_at: null,
}

beforeEach(() => useProjectStore.getState().reset())

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('PlaylistStart', () => {
  it('builds a project from the chosen playlist and opens it', async () => {
    vi.spyOn(gamApi, 'playlists').mockResolvedValue([playlist])
    const create = vi
      .spyOn(projectsApi, 'createFromPlaylist')
      .mockResolvedValue({ id: 'new-1' } as Project)
    show()
    await userEvent.click(screen.getByRole('button', { name: /from a gam playlist/i }))
    expect(
      await screen.findByRole('option', { name: 'The financial crisis (5 items)' })
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /build video/i }))
    expect(create).toHaveBeenCalledWith('p1', '')
    expect(await screen.findByText('Opened project')).toBeInTheDocument()
  })

  it('does not ask GAM until it is opened, and says when GAM cannot answer', async () => {
    const error = new AxiosError('failed')
    // @ts-expect-error - a minimal response is all apiErrorMessage reads
    error.response = {
      data: {
        detail: {
          code: 'gam_without_playlists',
          message: 'This version of the asset library has no playlists. Update GAM.',
        },
      },
    }
    const list = vi.spyOn(gamApi, 'playlists').mockRejectedValue(error)
    show()
    expect(list).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /from a gam playlist/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /no playlists\. Update GAM/
    )
  })

  it('says so when there are no playlists', async () => {
    vi.spyOn(gamApi, 'playlists').mockResolvedValue([])
    show()
    await userEvent.click(screen.getByRole('button', { name: /from a gam playlist/i }))
    expect(await screen.findByText(/no playlists in GAM yet/i)).toBeInTheDocument()
  })
})
