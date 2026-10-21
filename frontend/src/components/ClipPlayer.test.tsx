import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import ClipPlayer from '@/components/ClipPlayer'

const reel: GamAsset = {
  id: 'g1',
  name: 'Interview',
  asset_type: 'video',
  duration_seconds: 60,
  width: null,
  height: null,
  file_url: 'https://gam.test/f',
  thumb_url: null,
  credit: '',
  parent_asset_id: null,
  in_point: null,
  out_point: null,
  missing: false,
}

const spec: VideoSpec = {
  title: 'T',
  assets: { v: { from: 'gam', id: 'g1' } },
  segments: [
    {
      id: 's1',
      kind: 'scene',
      visual: { asset: 'v', trim: { in: 10, out: 16 } },
      narration: { beats: [{ id: 'b1', text: 'Hello' }] },
    },
  ],
}

function player(onChange = vi.fn()) {
  render(
    <ClipPlayer
      spec={spec}
      index={0}
      segment={spec.segments[0]}
      asset={reel}
      onChange={onChange}
      onClose={vi.fn()}
    />
  )
  return onChange
}

describe('ClipPlayer', () => {
  it('shows the trimmed window and its length', () => {
    player()
    expect(screen.getByLabelText('in point')).toHaveTextContent('0:10.0')
    expect(screen.getByLabelText('out point')).toHaveTextContent('0:16.0')
    expect(screen.getByText(/6 s of footage/)).toBeInTheDocument()
  })

  it('nudges the out point', async () => {
    const onChange = player()
    await userEvent.click(screen.getByRole('button', { name: 'out +0.1 s' }))
    expect(onChange.mock.calls[0][0].segments[0].visual.trim).toEqual({
      in: 10,
      out: 16.1,
    })
  })

  it('plays the whole clip again', async () => {
    const onChange = player()
    await userEvent.click(screen.getByRole('button', { name: 'Whole clip' }))
    expect(onChange.mock.calls[0][0].segments[0].visual.trim).toBeUndefined()
  })

  it('fixes the scene to the footage’s length', async () => {
    const onChange = player()
    await userEvent.click(screen.getByRole('button', { name: 'Match footage' }))
    expect(onChange.mock.calls[0][0].segments[0].duration).toEqual({ fixed: 6 })
  })

  it('says the footage is cut short when the narration is shorter', () => {
    player()
    expect(screen.getByRole('status')).toHaveTextContent('so its last 3.5 s aren’t shown')
  })
})
