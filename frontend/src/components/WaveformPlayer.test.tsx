import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WaveformPlayer from '@/components/WaveformPlayer'
import { gamApi, type GamWaveform } from '@/api/gam'
import { useThemeStore } from '@/stores/theme'

// jsdom has no canvas, so wavesurfer cannot draw here. What matters is what it is
// handed: the page's own <audio> element, and always peaks (never left to fetch).
const surfer = vi.hoisted(() => ({
  create: vi.fn(),
  destroy: vi.fn(),
}))
vi.mock('wavesurfer.js', () => ({
  default: {
    create: (options: unknown) => {
      surfer.create(options)
      return { destroy: surfer.destroy }
    },
  },
}))

interface CreateOptions {
  media: HTMLMediaElement
  peaks: number[][]
  duration?: number
  height: number
  waveColor: string
}

function lastCreateOptions(): CreateOptions {
  return surfer.create.mock.lastCall?.[0] as CreateOptions
}

function renderPlayer(compact = false) {
  const view = render(
    <WaveformPlayer
      assetId="m1"
      src="https://gam.test/media/m1.mp3?sig=x"
      name="Caravan theme"
      compact={compact}
    />
  )
  return { ...view, audio: view.container.querySelector('audio') as HTMLAudioElement }
}

function pending() {
  vi.spyOn(gamApi, 'peaks').mockReturnValue(new Promise(() => {}))
}

beforeEach(() => {
  surfer.create.mockClear()
  surfer.destroy.mockClear()
  useThemeStore.setState({ theme: 'light' })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WaveformPlayer', () => {
  it('draws GAM’s peaks over the page’s own audio element', async () => {
    const peaks = vi
      .spyOn(gamApi, 'peaks')
      .mockResolvedValue({ duration: 92, peaks: [0.2, 1, 0.5] })
    const { audio } = renderPlayer()

    await waitFor(() => expect(lastCreateOptions().peaks).toEqual([[0.2, 1, 0.5]]))
    expect(peaks).toHaveBeenCalledWith('m1')
    expect(lastCreateOptions().media).toBe(audio)
    expect(lastCreateOptions().duration).toBe(92)
    // The native control is gone; this component is the control now.
    expect(audio).not.toHaveAttribute('controls')
    expect(screen.getByLabelText('Listen to Caravan theme')).toBe(audio)
  })

  it('scrubs on a flat line until the peaks arrive, then swaps them in', async () => {
    let resolve: (value: GamWaveform) => void = () => {}
    vi.spyOn(gamApi, 'peaks').mockReturnValue(new Promise((r) => (resolve = r)))
    renderPlayer()

    // Never created without peaks: that is what would make it download the whole file.
    expect(lastCreateOptions().peaks).toEqual([[0]])

    await act(async () => resolve({ duration: 92, peaks: [0.4, 1] }))

    expect(surfer.destroy).toHaveBeenCalledTimes(1)
    expect(lastCreateOptions().peaks).toEqual([[0.4, 1]])
  })

  it('keeps the flat line when GAM has no waveform', async () => {
    const peaks = vi.spyOn(gamApi, 'peaks').mockRejectedValue(new Error('422'))
    renderPlayer()

    await waitFor(() => expect(peaks).toHaveBeenCalled())
    expect(surfer.create).toHaveBeenCalledTimes(1)
    expect(lastCreateOptions().peaks).toEqual([[0]])
  })

  it('knows the length from the waveform before a soundtrack card loads its audio', async () => {
    vi.spyOn(gamApi, 'peaks').mockResolvedValue({ duration: 125, peaks: [1] })
    const { audio } = renderPlayer(true)

    // A card does not fetch its audio until asked; GAM's measurement stands in.
    expect(audio).toHaveAttribute('preload', 'none')
    expect(await screen.findByText('0:00 / 2:05')).toBeInTheDocument()
    expect(lastCreateOptions().height).toBe(32)
  })

  it('plays and pauses the element', async () => {
    pending()
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    const pause = vi
      .spyOn(HTMLMediaElement.prototype, 'pause')
      .mockImplementation(() => {})
    const user = userEvent.setup()
    const { audio } = renderPlayer()

    await user.click(screen.getByRole('button', { name: 'Play Caravan theme' }))
    expect(play).toHaveBeenCalledTimes(1)

    // The button follows the element, not its own clicks.
    Object.defineProperty(audio, 'paused', { configurable: true, value: false })
    fireEvent.play(audio)
    await user.click(screen.getByRole('button', { name: 'Pause Caravan theme' }))
    expect(pause).toHaveBeenCalledTimes(1)
  })

  it('seeks with the arrow keys, within the recording', () => {
    pending()
    const { audio } = renderPlayer()
    Object.defineProperty(audio, 'duration', { configurable: true, value: 8 })
    fireEvent.loadedMetadata(audio)
    const slider = screen.getByRole('slider', { name: 'Position in Caravan theme' })

    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(5)
    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(audio.currentTime).toBe(8)
    fireEvent.keyDown(slider, { key: 'ArrowLeft' })
    expect(audio.currentTime).toBe(3)
  })

  it('redraws in the dark theme’s colours when the theme flips', () => {
    pending()
    renderPlayer()
    const light = lastCreateOptions().waveColor

    act(() => useThemeStore.setState({ theme: 'dark' }))

    expect(surfer.destroy).toHaveBeenCalledTimes(1)
    expect(lastCreateOptions().waveColor).not.toBe(light)
  })
})
