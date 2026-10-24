import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import CardSettings from '@/components/CardSettings'
import LookSettings from '@/components/LookSettings'
import OverlayTextSettings from '@/components/OverlayTextSettings'
import PanelSettings from '@/components/PanelSettings'
import ProjectDefaults from '@/components/ProjectDefaults'
import SceneSettings from '@/components/SceneSettings'
import VoiceSettings from '@/components/VoiceSettings'
import WatermarkSettings from '@/components/WatermarkSettings'

let latest: VideoSpec
function Sections({
  start,
  children,
}: {
  start: VideoSpec
  children: (p: { spec: VideoSpec; set: (s: VideoSpec) => void }) => React.ReactNode
}) {
  const [spec, setSpec] = useState(start)
  latest = spec
  return <>{children({ spec, set: setSpec })}</>
}

const blank: VideoSpec = { title: 'My film', segments: [] }

describe('the project-wide settings sections', () => {
  it('looks: a gradient, a solid colour, and how pictures are fitted', () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <LookSettings spec={spec} gamAssets={{}} onChange={set} />}
      </Sections>
    )
    fireEvent.change(screen.getByLabelText('Gradient angle'), { target: { value: '90' } })
    fireEvent.change(screen.getByLabelText('Fit pictures'), { target: { value: 'crop' } })
    expect(latest.style).toEqual({ background: { angle: 90 }, fit: 'crop' })
    fireEvent.change(screen.getByLabelText('Background'), { target: { value: 'solid' } })
    expect(screen.queryByLabelText('Gradient angle')).not.toBeInTheDocument()
    expect(latest.style?.background).toEqual({ angle: 90, type: 'solid' })
  })

  it('cards: length, zoom and the type sizes of each kind of card', async () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <CardSettings spec={spec} onChange={set} />}
      </Sections>
    )
    fireEvent.change(screen.getByLabelText('Card length'), { target: { value: '5' } })
    await userEvent.click(screen.getByRole('checkbox', { name: /Slow zoom/ }))
    fireEvent.change(
      screen.getByLabelText('Chapter card heading size, % of the height'),
      {
        target: { value: '4' },
      }
    )
    expect(latest.style?.cards).toEqual({
      seconds: 5,
      motion: true,
      chapter: { title_pct: 4 },
    })
  })

  it('panels: quote and code are set apart', () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <PanelSettings spec={spec} onChange={set} />}
      </Sections>
    )
    fireEvent.change(screen.getByLabelText('Quote position'), {
      target: { value: 'top' },
    })
    fireEvent.change(screen.getByLabelText('Code text size, % of the height'), {
      target: { value: '5' },
    })
    expect(latest.style?.quote).toEqual({ position: 'top' })
    expect(latest.style?.code).toEqual({ size_pct: 5 })
  })

  it('the default transition is set with its length, and removed when set to a cut', () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <ProjectDefaults spec={spec} onChange={set} />}
      </Sections>
    )
    expect(screen.queryByLabelText('Transition length')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Transition between scenes'), {
      target: { value: 'dissolve' },
    })
    fireEvent.change(screen.getByLabelText('Transition length'), {
      target: { value: '1' },
    })
    expect(latest.style?.transition).toEqual({ style: 'dissolve', duration: 1 })
  })

  it('the watermark is on with its defaults written in, and its text and corner can change', async () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => (
          <WatermarkSettings spec={spec} gamAssets={{}} onChange={set} />
        )}
      </Sections>
    )
    await userEvent.click(screen.getByRole('checkbox'))
    expect(latest.chrome?.watermark).toMatchObject({
      position: 'bottom-right',
      scale_pct: 6,
    })
    fireEvent.change(screen.getByLabelText('Watermark text'), {
      target: { value: 'geckopico' },
    })
    fireEvent.change(screen.getByLabelText('Watermark corner'), {
      target: { value: 'top-left' },
    })
    expect(latest.chrome?.watermark).toMatchObject({
      text: 'geckopico',
      position: 'top-left',
    })
    await userEvent.click(screen.getByRole('checkbox'))
    expect(latest.chrome).toBeUndefined()
  })

  it('text on every scene: fixed text, or the title', async () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <OverlayTextSettings spec={spec} onChange={set} />}
      </Sections>
    )
    await userEvent.click(screen.getByRole('checkbox', { name: 'Text on every scene' }))
    fireEvent.change(
      screen.getByLabelText('Text on every scene', {
        selector: 'input[type=text], input:not([type])',
      }),
      {
        target: { value: '#salt' },
      }
    )
    expect(latest.chrome?.overlay_text).toMatchObject({ mode: 'fixed', text: '#salt' })
    fireEvent.change(screen.getByLabelText('Text shows'), { target: { value: 'title' } })
    expect(screen.queryByLabelText('Text position')).toBeInTheDocument()
    expect(latest.chrome?.overlay_text).toMatchObject({ mode: 'title' })
  })

  it('a decimal can be typed into a field whose first digit alone is out of range', async () => {
    render(
      <Sections start={blank}>
        {({ spec, set }) => <VoiceSettings spec={spec} onChange={set} />}
      </Sections>
    )
    const speed = screen.getByLabelText('Speaking speed')
    await userEvent.clear(speed)
    await userEvent.type(speed, '0.9')
    expect(latest.voice?.speed).toBe(0.9)
    await userEvent.clear(speed)
    await userEvent.type(speed, '7')
    expect(latest.voice?.speed).toBe(0.9) // refused: the spec would not take 7
  })
})

describe('a scene’s opt-out from the project overlays', () => {
  const withWave: VideoSpec = {
    title: 'T',
    chrome: { waveform: {} },
    segments: [
      { id: 's1', kind: 'scene' },
      { id: 'outro', kind: 'scene', role: 'outro' },
    ],
  }

  it('is offered only when something is drawn project-wide', () => {
    render(
      <SceneSettings
        spec={blank}
        index={0}
        segment={{ id: 's', kind: 'scene' }}
        gamAssets={{}}
        onChange={() => {}}
      />
    )
    expect(
      screen.queryByLabelText('Project overlays on this scene')
    ).not.toBeInTheDocument()
  })

  it('hides them on one scene, and says what the default is for an outro', () => {
    render(
      <Sections start={withWave}>
        {({ spec, set }) => (
          <>
            <SceneSettings
              spec={spec}
              index={0}
              segment={spec.segments[0]}
              gamAssets={{}}
              onChange={set}
            />
          </>
        )}
      </Sections>
    )
    fireEvent.change(screen.getByLabelText('Project overlays on this scene'), {
      target: { value: 'false' },
    })
    expect(latest.segments[0].chrome).toBe(false)
    fireEvent.change(screen.getByLabelText('Project overlays on this scene'), {
      target: { value: '' },
    })
    expect('chrome' in latest.segments[0]).toBe(false)
  })

  it('names an outro’s default as off', () => {
    render(
      <SceneSettings
        spec={withWave}
        index={1}
        segment={withWave.segments[1]}
        gamAssets={{}}
        onChange={() => {}}
      />
    )
    expect(screen.getByRole('option', { name: 'Default (off)' })).toBeInTheDocument()
  })
})
