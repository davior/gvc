import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import SoundtrackPanel from '@/components/SoundtrackPanel'

const start: VideoSpec = {
  title: 'T',
  assets: {
    a_theme: { from: 'gam', id: 'g1', label: 'Theme' },
    a_close: { from: 'gam', id: 'g2', label: 'Close' },
  },
  segments: [
    { id: 's1', kind: 'scene', label: 'Valley' },
    { id: 's2', kind: 'scene', label: 'River' },
  ],
  audio_tracks: [
    {
      id: 'm_1',
      asset: 'a_theme',
      start: { segment: 's1', edge: 'start' },
      end: { segment: 's2', edge: 'end' },
    },
    { id: 'm_2', asset: 'a_close', start: { segment: 's2', edge: 'start' } },
  ],
}

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return <SoundtrackPanel spec={spec} gamAssets={{}} onChange={setSpec} />
}

describe('SoundtrackPanel', () => {
  it('places a track between scenes and crossfades into the next', async () => {
    render(<Harness />)
    const theme = screen.getByRole('region', { name: 'Theme' })
    fireEvent.change(within(theme).getByLabelText('Until'), {
      target: { value: 'start:s2' },
    })
    expect(latest.audio_tracks![0].end).toEqual({ segment: 's2', edge: 'start' })

    const close = screen.getByRole('region', { name: 'Close' })
    await userEvent.click(
      within(close).getByRole('button', { name: /Crossfade from the track above/ })
    )
    expect(latest.audio_tracks![1].start).toEqual({
      segment: 's2',
      edge: 'start',
      offset: -3,
    })
    expect(latest.audio_tracks![0].fade_out).toBe(3)

    fireEvent.change(within(close).getByLabelText('Volume'), { target: { value: '0.5' } })
    expect(latest.audio_tracks![1].volume).toBe(0.5)
    expect(within(close).getByText('50%')).toBeInTheDocument()

    // Music is ducked and looped unless told otherwise; an effect is neither.
    expect(within(close).getByLabelText('Quieter under narration')).toBeChecked()
    fireEvent.change(within(close).getByLabelText('Kind of track'), {
      target: { value: 'sfx' },
    })
    expect(
      within(screen.getByRole('region', { name: 'Close' })).getByLabelText('Loop to fill')
    ).not.toBeChecked()
  })

  it('offers a player only for a track whose file GAM can serve', () => {
    const gam = (id: string, over: object = {}) => ({
      id,
      name: id,
      asset_type: 'audio',
      duration_seconds: 10,
      width: null,
      height: null,
      file_url: `https://gam.test/media/${id}?sig=x`,
      thumb_url: null,
      credit: '',
      parent_asset_id: null,
      in_point: null,
      out_point: null,
      missing: false,
      ...over,
    })
    render(
      <SoundtrackPanel
        spec={start}
        gamAssets={{ g1: gam('g1'), g2: gam('g2', { missing: true }) }}
        onChange={() => {}}
      />
    )
    expect(screen.getByLabelText('Listen to g1')).toHaveAttribute(
      'src',
      'https://gam.test/media/g1?sig=x'
    )
    expect(screen.queryByLabelText('Listen to g2')).not.toBeInTheDocument()
  })
})
