import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import OutputSettings from '@/components/OutputSettings'
import VoiceSettings from '@/components/VoiceSettings'

const start: VideoSpec = { title: 'T', segments: [] }

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return (
    <>
      <OutputSettings spec={spec} onChange={setSpec} />
      <VoiceSettings spec={spec} onChange={setSpec} />
    </>
  )
}

describe('Output and voice settings', () => {
  it('shows the spec defaults and changes the file settings', async () => {
    render(<Harness />)
    expect(screen.getByLabelText('Shape')).toHaveValue('16:9')
    expect(screen.getByLabelText('Frames per second')).toHaveValue(30)

    fireEvent.change(screen.getByLabelText('Shape'), { target: { value: '9:16' } })
    fireEvent.change(screen.getByLabelText('Size'), { target: { value: '4k' } })
    fireEvent.change(screen.getByLabelText('Subtitles'), { target: { value: 'burn' } })
    await userEvent.click(screen.getByRole('checkbox', { name: /Cover picture/ }))
    expect(latest.output).toEqual({
      aspect: '9:16',
      resolution: '4k',
      subtitles: 'burn',
      thumbnail: false,
    })
  })

  it('ignores a frame rate the spec would refuse', () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Frames per second'), {
      target: { value: '120' },
    })
    expect(latest.output).toBeUndefined()
    fireEvent.change(screen.getByLabelText('Frames per second'), {
      target: { value: '24' },
    })
    expect(latest.output).toEqual({ fps: 24 })
  })

  it('sets the narrator: a named voice, a speed and the pauses', () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Narrator voice'), {
      target: { value: 'Rachel' },
    })
    fireEvent.change(screen.getByLabelText('Speaking speed'), {
      target: { value: '0.9' },
    })
    fireEvent.change(screen.getByLabelText('Pause at a heading, milliseconds'), {
      target: { value: '1200' },
    })
    expect(latest.voice).toEqual({
      voice: 'Rachel',
      speed: 0.9,
      pauses: { heading_ms: 1200 },
    })
  })
})
