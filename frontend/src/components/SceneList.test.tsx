import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import SceneList from '@/components/SceneList'

const start: VideoSpec = {
  title: 'By hand',
  segments: [
    {
      id: 's_title',
      kind: 'card',
      label: 'Title',
      card: { variant: 'title', title: 'By hand' },
    },
    {
      id: 's_1',
      kind: 'scene',
      label: 'Desert',
      narration: { beats: [{ id: 'b1', text: '' }] },
    },
  ],
}

let latest: VideoSpec = start

function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return <SceneList spec={spec} onChange={setSpec} />
}

describe('SceneList', () => {
  it('builds a video scene by scene', async () => {
    render(<Harness />)

    fireEvent.change(
      within(screen.getByRole('region', { name: 'Desert' })).getByLabelText('Narration'),
      { target: { value: 'Salt crossed the desert.' } }
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add a scene' }))
    const added = screen.getByRole('region', { name: 'Scene 2' })
    fireEvent.change(within(added).getByLabelText('Narration'), {
      target: { value: 'The market.\n\nAt dawn.' },
    })
    await userEvent.click(within(added).getByRole('button', { name: 'Move up' }))

    expect(latest.segments.map((s) => s.label)).toEqual(['Title', 'Scene 2', 'Desert'])
    expect(latest.segments[1].narration?.beats).toEqual([
      { id: 'b1', text: 'The market.' },
      { id: 'b2', text: 'At dawn.' },
    ])
    expect(latest.segments[2].narration?.beats[0].text).toBe('Salt crossed the desert.')
  })

  it('edits a card title and removes a segment', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Card title'), {
      target: { value: 'Salt Road' },
    })
    expect(latest.segments[0].card?.title).toBe('Salt Road')

    await userEvent.click(
      within(screen.getByRole('region', { name: 'Desert' })).getByRole('button', {
        name: 'Remove',
      })
    )
    expect(latest.segments.map((s) => s.id)).toEqual(['s_title'])
  })
})
