import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import CreditsSettings from '@/components/CreditsSettings'
import OverlayEditor from '@/components/OverlayEditor'

const start: VideoSpec = {
  title: 'T',
  segments: [
    {
      id: 's1',
      kind: 'scene',
      narration: {
        beats: [
          { id: 'b1', text: 'One.' },
          { id: 'b2', text: 'Two.' },
        ],
      },
    },
    { id: 's2', kind: 'scene', label: 'The river' },
  ],
}

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return (
    <>
      <OverlayEditor
        spec={spec}
        index={0}
        segment={spec.segments[0]}
        gamAssets={{}}
        onChange={setSpec}
      />
      <CreditsSettings spec={spec} onChange={setSpec} />
    </>
  )
}

describe('OverlayEditor', () => {
  it('adds a lower third for the whole scene, then times it to a line and a later scene', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('button', { name: /Name and role/ }))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada Lovelace' } })
    expect(latest.segments[0].overlays).toEqual([
      { id: 'o_1', type: 'lower_third', title: 'Ada Lovelace', subtitle: 'Role' },
    ])

    fireEvent.change(screen.getByLabelText('From'), { target: { value: 'start::b2' } })
    expect(latest.segments[0].overlays?.[0].show).toEqual({
      from: { beat: 'b2', edge: 'start' },
      to: { edge: 'end' },
    })
    fireEvent.change(screen.getByLabelText('Until'), { target: { value: 'start:s2' } })
    fireEvent.change(screen.getByLabelText('Until offset in seconds'), {
      target: { value: '1.5' },
    })
    expect(latest.segments[0].overlays?.[0].show?.to).toEqual({
      segment: 's2',
      edge: 'start',
      offset: 1.5,
    })
    expect(screen.getAllByRole('option', { name: 'start of The river' })).toHaveLength(2)

    // Back to the whole scene.
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '' } })
    expect(latest.segments[0].overlays?.[0]).not.toHaveProperty('show')

    await userEvent.click(screen.getByRole('button', { name: 'Remove from screen' }))
    expect(latest.segments[0].overlays).toEqual([])
  })

  it('turns credits on with extra lines, and off again', async () => {
    render(<Harness />)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Credits' }))
    expect(latest.credits).toMatchObject({ auto: true, card: true, description: true })
    await userEvent.click(screen.getByRole('checkbox', { name: /on a card at the end/ }))
    const extra = screen.getByLabelText('More credit lines')
    fireEvent.change(extra, { target: { value: ' Narrated by Rex \n\n' } })
    fireEvent.blur(extra)
    expect(latest.credits).toMatchObject({ card: false, extra: ['Narrated by Rex'] })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Credits' }))
    expect(latest).not.toHaveProperty('credits')
  })
})
