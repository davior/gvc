import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { rendersApi, type Estimate, type Render } from '@/api/renders'
import RenderPanel from '@/components/RenderPanel'
import { useRenderStore } from '@/stores/renders'

const estimate = (overrides: Partial<Estimate> = {}): Estimate => ({
  seconds: 95,
  seconds_is_floor: false,
  narration_chars: 1840,
  blocks_render: [],
  blocks_preview: [],
  ...overrides,
})

const done: Render = {
  id: 'r1',
  project_id: 'p',
  version: 3,
  preview: false,
  status: 'done',
  stage: '',
  progress: 100,
  detail: '',
  error: null,
  warnings: ['Blends were joined as cuts.'],
  duration: 94.2,
  size_bytes: 12 * 1024 * 1024,
  narration_chars: 1840,
  video_url: '/media/renders/r1/video.mp4?exp=1&sig=x',
  subtitles_url: '/media/renders/r1/subtitles.srt?exp=1&sig=x',
  poster_url: null,
  created_at: '2026-10-16T00:00:00',
  updated_at: '2026-10-16T00:00:00',
}

beforeEach(() => useRenderStore.getState().reset())
afterEach(() => vi.restoreAllMocks())

describe('RenderPanel', () => {
  it('says how long, and plays and offers the latest render', async () => {
    vi.spyOn(rendersApi, 'list').mockResolvedValue([done])
    vi.spyOn(rendersApi, 'estimate').mockResolvedValue(estimate())
    render(<RenderPanel projectId="p" dirty={false} version={3} />)

    expect(
      await screen.findByText(/About 1:35 long, with 1,840 characters/)
    ).toBeInTheDocument()
    expect(document.querySelector('video')?.getAttribute('src')).toBe(done.video_url)
    expect(screen.getByText('Blends were joined as cuts.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download video' })).toHaveAttribute(
      'href',
      done.video_url
    )
    expect(screen.getByText('12.0 MB')).toBeInTheDocument()
  })

  it('will not render unsaved edits, and says why a full render is blocked', async () => {
    vi.spyOn(rendersApi, 'list').mockResolvedValue([])
    vi.spyOn(rendersApi, 'estimate').mockResolvedValue(
      estimate({ blocks_render: ['Footage still to find: “ruins”.'] })
    )
    const { rerender } = render(<RenderPanel projectId="p" dirty={true} version={3} />)
    expect(await screen.findByText('Footage still to find: “ruins”.')).toBeInTheDocument()
    expect(screen.getByText(/Save first/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()

    rerender(<RenderPanel projectId="p" dirty={false} version={3} />)
    expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Render' })).toBeDisabled()
  })

  it('starts a preview and shows its progress', async () => {
    vi.spyOn(rendersApi, 'list').mockResolvedValue([])
    vi.spyOn(rendersApi, 'estimate').mockResolvedValue(estimate())
    const queued: Render = {
      ...done,
      id: 'r2',
      status: 'processing',
      stage: 'Narrating',
      progress: 30,
      detail: 'shot 2 of 6',
      video_url: null,
      preview: true,
      warnings: [],
    }
    const startSpy = vi.spyOn(rendersApi, 'start').mockResolvedValue(queued)
    render(<RenderPanel projectId="p" dirty={false} version={3} />)
    await screen.findByText(/About/)

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))

    expect(startSpy).toHaveBeenCalledWith('p', true)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '30')
    expect(
      screen.getByText(/Preview of version 3: Narrating \(shot 2 of 6\)/)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Render' })).toBeDisabled()
  })
})
