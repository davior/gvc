import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { Segment, VideoSpec } from '@/api/projects'
import VisualStrip from '@/components/VisualStrip'

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
})
