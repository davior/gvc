import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import WaveformSettings from '@/components/WaveformSettings'

const start: VideoSpec = { title: 'T', segments: [] }

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return <WaveformSettings spec={spec} onChange={setSpec} />
}

describe('WaveformSettings', () => {
  it('turns the wave on with the settings Notes defaults to, edits them, and off again', async () => {
    render(<Harness />)
    expect(screen.queryByLabelText('Wave style')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox'))
    expect(latest.chrome?.waveform).toEqual({
      mode: 'line',
      color: '#00ff41',
      opacity: 0.7,
      position: 'bottom',
      height_pct: 22,
      scrim: 0.45,
    })

    fireEvent.change(screen.getByLabelText('Wave style'), { target: { value: 'p2p' } })
    fireEvent.change(screen.getByLabelText('Wave position'), {
      target: { value: 'center' },
    })
    expect(latest.chrome?.waveform).toMatchObject({ mode: 'p2p', position: 'center' })

    // Off removes the block, and the empty `chrome` with it.
    await userEvent.click(screen.getByRole('checkbox'))
    expect(latest.chrome).toBeUndefined()
  })
})
