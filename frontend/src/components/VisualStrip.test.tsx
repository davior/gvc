import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { Segment, VideoSpec } from '@/api/projects'
import { generationsApi, type Generation } from '@/api/generations'
import VisualStrip from '@/components/VisualStrip'
import { useGenerationStore } from '@/stores/generations'

const reel: GamAsset = {
  id: 'g1',
  name: 'Archive interview',
  asset_type: 'video',
  duration_seconds: 1800,
  width: null,
  height: null,
  file_url: 'https://gam.test/f',
  thumb_url: 'https://gam.test/t.jpg',
  credit: '',
  parent_asset_id: null,
  in_point: null,
  out_point: null,
  missing: false,
}

const spec: VideoSpec = {
  title: 'T',
  assets: {
    a_reel: { from: 'gam', id: 'g1' },
    a_gone: { from: 'gam', id: 'g9', label: 'Old map' },
    a_note: { from: 'notes', url: '/media/u1/map.png', type: 'image' },
    a_ruins: { from: 'search', query: 'ruins at dusk', status: 'unresolved' },
  },
  segments: [],
}

function strip(segment: Segment) {
  return render(
    <VisualStrip
      spec={spec}
      segment={segment}
      gamAssets={{ g1: reel, g9: null }}
      onFind={vi.fn()}
      onRemove={vi.fn()}
    />
  )
}

describe('VisualStrip', () => {
  it('shows the footage with its thumbnail and trim', () => {
    strip({
      id: 's',
      kind: 'scene',
      visual: { asset: 'a_reel', trim: { in: 733.5, out: 742 } },
    })
    expect(screen.getByText('Archive interview')).toBeInTheDocument()
    expect(screen.getByText('12:13–12:22')).toBeInTheDocument()
    expect(document.querySelector('img')?.getAttribute('src')).toBe(
      'https://gam.test/t.jpg'
    )
  })

  it('says why there is nothing to show', () => {
    const { unmount } = strip({ id: 's', kind: 'scene', visual: { asset: 'a_gone' } })
    expect(screen.getByText('No longer in the library')).toBeInTheDocument()
    unmount()
    strip({ id: 's', kind: 'scene', visual: { asset: 'a_note' } })
    expect(screen.getByText('Still in the note')).toBeInTheDocument()
  })

  it('names what a placeholder is waiting for', () => {
    strip({ id: 's', kind: 'scene', visual: { asset: 'a_ruins' } })
    expect(screen.getByText('To find: “ruins at dusk”')).toBeInTheDocument()
  })

  it('offers to find footage for a scene without any', () => {
    strip({ id: 's', kind: 'scene' })
    expect(screen.getByRole('button', { name: 'Find footage' })).toBeInTheDocument()
  })

  describe('a picture to generate', () => {
    const row = (over: Partial<Generation>): Generation => ({
      id: 'g',
      project_id: 'p',
      asset_key: 'a_dam',
      kind: 'text_to_image',
      prompt: 'A dam',
      model_label: 'FLUX',
      status: 'queued',
      stage: '',
      progress: 0,
      detail: '',
      error: null,
      result_ids: [],
      used_id: null,
      estimate: null,
      created_at: '',
      updated_at: '',
      ...over,
    })
    const withDam = (result?: string): VideoSpec => ({
      ...spec,
      assets: {
        ...spec.assets,
        a_dam: {
          from: 'generate',
          type: 'image',
          prompt: 'A dam',
          ...(result ? { status: 'ready', result: { from: 'gam', id: result } } : {}),
        },
      },
    })
    const show = (s: VideoSpec, onGenerate = vi.fn()) =>
      render(
        <VisualStrip
          spec={s}
          segment={{ id: 's', kind: 'scene', visual: { asset: 'a_dam' } }}
          gamAssets={{ g1: reel }}
          onFind={vi.fn()}
          onRemove={vi.fn()}
          onGenerate={onGenerate}
        />
      )
    afterEach(() => {
      useGenerationStore.getState().reset()
      vi.restoreAllMocks()
    })

    it('offers to generate it', async () => {
      const onGenerate = vi.fn()
      show(withDam(), onGenerate)
      await userEvent.click(screen.getByRole('button', { name: 'Generate…' }))
      expect(onGenerate).toHaveBeenCalledWith('a_dam')
    })

    it('shows a running one with Stop', async () => {
      useGenerationStore.setState({
        rows: [row({ status: 'processing', stage: 'Generating', detail: '0:12' })],
      })
      const cancel = vi.spyOn(generationsApi, 'cancel').mockResolvedValue(row({}))
      show(withDam())
      expect(screen.getByText('Generating · 0:12')).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Stop' }))
      expect(cancel).toHaveBeenCalledWith('g')
    })

    it('says why one failed and offers another go', () => {
      useGenerationStore.setState({
        rows: [row({ status: 'error', error: 'Content policy' })],
      })
      show(withDam())
      expect(screen.getByText('Content policy')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    })

    it('shows the one chosen and the other outputs', () => {
      useGenerationStore.setState({
        rows: [row({ status: 'done', result_ids: ['g1', 'g2'], used_id: 'g1' })],
      })
      show(withDam('g1'))
      expect(screen.getByText('Archive interview')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Output 1' })).toHaveAttribute(
        'aria-pressed',
        'true'
      )
      expect(screen.getByRole('button', { name: 'Output 2' })).toHaveAttribute(
        'aria-pressed',
        'false'
      )
      expect(screen.queryByRole('button', { name: 'Generate…' })).toBeNull()
    })
  })
})
