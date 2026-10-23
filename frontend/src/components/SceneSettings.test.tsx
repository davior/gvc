import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import SceneSettings from '@/components/SceneSettings'

const map: GamAsset = {
  id: 'p',
  name: 'Map',
  asset_type: 'image',
  duration_seconds: null,
  width: 1600,
  height: 900,
  file_url: 'https://gam.test/p.png',
  thumb_url: null,
  credit: '',
  parent_asset_id: null,
  in_point: null,
  out_point: null,
  missing: false,
}

const start: VideoSpec = {
  title: 'T',
  output: { aspect: '16:9' },
  style: { transition: { style: 'fade', duration: 0.6 } },
  assets: { a_map: { from: 'gam', id: 'p' } },
  segments: [
    { id: 's0', kind: 'card', card: { variant: 'title', title: 'T' } },
    { id: 's1', kind: 'scene', visual: { asset: 'a_map' } },
  ],
}

let latest = start
function Harness() {
  const [spec, setSpec] = useState(start)
  latest = spec
  return (
    <SceneSettings
      spec={spec}
      index={1}
      segment={spec.segments[1]}
      gamAssets={{ p: map }}
      onChange={setSpec}
    />
  )
}

describe('SceneSettings', () => {
  it('sets a transition of its own, keeping the project duration until one is typed', () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Transition into this scene'), {
      target: { value: 'dissolve' },
    })
    expect(latest.segments[1].transition_in).toEqual({ style: 'dissolve' })
    expect(screen.getByLabelText('Transition length in seconds')).toHaveAttribute(
      'placeholder',
      '0.6'
    )
    fireEvent.change(screen.getByLabelText('Transition length in seconds'), {
      target: { value: '1.2' },
    })
    expect(latest.segments[1].transition_in).toEqual({ style: 'dissolve', duration: 1.2 })
    fireEvent.change(screen.getByLabelText('Transition into this scene'), {
      target: { value: '' },
    })
    expect(latest.segments[1].transition_in).toBeUndefined()
  })

  it('moves the camera between two frames set over the picture', () => {
    render(<Harness />)
    fireEvent.change(screen.getByLabelText('Ken Burns move'), {
      target: { value: 'path' },
    })
    expect(latest.segments[1].visual?.motion?.effect).toBe('path')
    expect(screen.getByRole('button', { name: 'Start frame' })).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('End x'), { target: { value: '0.55' } })
    fireEvent.change(screen.getByLabelText('End w'), { target: { value: '0.3' } })
    expect(latest.segments[1].visual?.motion?.to).toEqual({ x: 0.55, y: 0.3, w: 0.3 })
    // Too far right for its width: brought back inside the picture.
    fireEvent.change(screen.getByLabelText('End x'), { target: { value: '0.9' } })
    expect(latest.segments[1].visual?.motion?.to?.x).toBe(0.7)
  })

  it('offers a camera move for a generated picture, naming the project default', () => {
    const spec: VideoSpec = {
      ...start,
      style: { ...start.style, motion: { effect: 'alternate' } },
      assets: {
        a_gen: {
          from: 'generate',
          type: 'image',
          prompt: 'A map',
          result: { from: 'gam', id: 'p' },
        },
      },
      segments: [
        start.segments[0],
        { id: 's1', kind: 'scene', visual: { asset: 'a_gen' } },
      ],
    }
    render(
      <SceneSettings
        spec={spec}
        index={1}
        segment={spec.segments[1]}
        gamAssets={{ p: map }}
        onChange={() => {}}
      />
    )
    expect(
      screen.getByRole('option', { name: 'Project default (Alternate zooms and pans)' })
    ).toBeInTheDocument()
  })
})
