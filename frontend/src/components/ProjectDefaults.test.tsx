import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import ProjectDefaults from '@/components/ProjectDefaults'

const start: VideoSpec = {
  title: 'T',
  style: { transition: { style: 'fade', duration: 0.6 } },
  segments: [],
}

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return <ProjectDefaults spec={spec} onChange={setSpec} />
}

describe('ProjectDefaults', () => {
  it('sets the move every still follows, and removes it again when set back to still', () => {
    render(<Harness />)
    expect(screen.queryByLabelText('Default Ken Burns amount')).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /two frames/ })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Default Ken Burns move'), {
      target: { value: 'alternate' },
    })
    expect(latest.style?.motion).toEqual({ effect: 'alternate' })

    fireEvent.change(screen.getByLabelText('Default Ken Burns amount'), {
      target: { value: '0.2' },
    })
    expect(latest.style?.motion).toEqual({ effect: 'alternate', amount: 0.2 })
    fireEvent.change(screen.getByLabelText('Default Ken Burns amount'), {
      target: { value: '' },
    })
    fireEvent.change(screen.getByLabelText('Default Ken Burns move'), {
      target: { value: 'none' },
    })
    expect(latest.style).toEqual({ transition: { style: 'fade', duration: 0.6 } })
  })
})
