import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  audioSummary,
  gamApi,
  musicSummary,
  type GamAsset,
  type GamHit,
  type GamSearch,
} from '@/api/gam'
import FootageSearch from '@/components/FootageSearch'

function asset(overrides: Partial<GamAsset> = {}): GamAsset {
  return {
    id: 'g1',
    name: 'Archive interview',
    asset_type: 'video',
    duration_seconds: 1800,
    width: null,
    height: null,
    file_url: 'https://gam.test/media/g1?sig=x',
    thumb_url: 'https://gam.test/media/g1.jpg?sig=x',
    credit: 'BBC Archive, 1971',
    parent_asset_id: null,
    in_point: null,
    out_point: null,
    missing: false,
    ...overrides,
  }
}

function result(hits: GamHit[], semantic = true): GamSearch {
  return { data: hits, total: hits.length, query: 'q', semantic, semantic_error: null }
}

const spoken: GamHit = {
  asset: asset(),
  score: 0.03,
  snippet: 'they talked about «water» all day',
  start_time: 734,
  end_time: 741.5,
}

// A picked track's player asks GAM for its waveform; left pending, as WaveformPlayer's
// own test covers what it draws.
beforeEach(() => {
  vi.spyOn(gamApi, 'peaks').mockReturnValue(new Promise(() => {}))
})
afterEach(() => vi.restoreAllMocks())

describe('FootageSearch', () => {
  it('finds where something is said and places that moment as b-roll', async () => {
    const search = vi.spyOn(gamApi, 'search').mockResolvedValue(result([spoken]))
    const onPick = vi.fn()
    render(
      <FootageSearch title="Footage" purpose="scene" onPick={onPick} onClose={vi.fn()} />
    )

    await userEvent.type(screen.getByLabelText('Search the asset library'), 'water')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(search).toHaveBeenCalledWith('water', 'video')
    expect(await screen.findByText('water', { selector: 'mark' })).toBeInTheDocument()
    expect(screen.getByText('at 12:14–12:21')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Archive interview/ }))
    expect(screen.getByText('Uses 12:13–12:22 (9 s)')).toBeInTheDocument()
    expect(screen.getByText('BBC Archive, 1971')).toBeInTheDocument()
    const video = document.querySelector('video')!
    expect(video.getAttribute('src')).toBe('https://gam.test/media/g1?sig=x#t=733.5,742')

    await userEvent.click(screen.getByRole('button', { name: 'Play with its sound' }))
    expect(onPick).toHaveBeenCalledWith(spoken, 'clip')
  })

  it('offers a picture as a picture', async () => {
    const map = {
      ...spoken,
      start_time: null,
      end_time: null,
      asset: asset({ asset_type: 'image', name: 'Map' }),
    }
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([map]))
    const onPick = vi.fn()
    render(
      <FootageSearch
        title="Footage"
        purpose="scene"
        initialQuery="map"
        onPick={onPick}
        onClose={vi.fn()}
      />
    )

    await userEvent.click(screen.getByRole('button', { name: 'Pictures' }))
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await userEvent.click(await screen.findByRole('button', { name: /Map/ }))

    expect(screen.getByText('A still picture')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Play with its sound' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Use this picture' }))
    expect(onPick).toHaveBeenCalledWith(map, 'broll')
  })

  it('sizes the moment the way a placeholder asked for', async () => {
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([spoken]))
    render(
      <FootageSearch
        title="Find: ruins"
        purpose="resolve"
        initialQuery="ruins"
        moment={{ min: 20 }}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await userEvent.click(
      await screen.findByRole('button', { name: /Archive interview/ })
    )
    expect(screen.getByText('Uses 12:07–12:27 (20 s)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use this' })).toBeInTheDocument()
  })

  it('says when only the word-matching half of the search ran', async () => {
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([], false))
    render(
      <FootageSearch
        title="F"
        purpose="scene"
        initialQuery="x"
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText(/Matched on words only/)).toBeInTheDocument()
    expect(screen.getByText('Nothing in the library matches.')).toBeInTheDocument()
  })

  it('says what a track sounds like, in the list and once picked', async () => {
    const track: GamHit = {
      asset: asset({
        id: 'm1',
        name: 'Caravan theme',
        asset_type: 'audio',
        thumb_url: null,
        music: {
          genres: ['Ambient'],
          moods: ['Tense'],
          instruments: [],
          bpm: 92,
          key: 'Am',
          vocals: false,
          energy: 'low',
        },
      }),
      score: 0.03,
      snippet: '',
      start_time: null,
      end_time: null,
    }
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([track]))
    render(
      <FootageSearch title="Music" purpose="track" onPick={vi.fn()} onClose={vi.fn()} />
    )

    await userEvent.type(screen.getByLabelText('Search the asset library'), 'tense')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))

    const line = 'Ambient, Tense · 92 BPM · Am · Low energy · Instrumental'
    expect(await screen.findByText(line)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Caravan theme/ }))
    expect(screen.getAllByText(line)).toHaveLength(2)
  })

  it('leaves the line out for a track nothing is known about', () => {
    expect(musicSummary(null)).toBe('')
    expect(
      musicSummary({
        genres: [],
        moods: [],
        instruments: [],
        bpm: null,
        key: null,
        vocals: null,
        energy: null,
      })
    ).toBe('')
  })

  it('puts the kind of audio first, so a voice memo stands out', () => {
    expect(audioSummary({ audio_kind: 'speech', music: null })).toBe('Speech')
    expect(audioSummary({ audio_kind: 'sfx', music: null })).toBe('Sound effect')
    expect(audioSummary({ audio_kind: 'music', music: null })).toBe('Music')
    const music = {
      genres: ['Ambient'],
      moods: [],
      instruments: [],
      bpm: null,
      key: null,
      vocals: null,
      energy: null,
    }
    expect(audioSummary({ audio_kind: 'music', music })).toBe('Ambient')
    expect(audioSummary({ audio_kind: null, music })).toBe('Ambient')
    expect(audioSummary({ audio_kind: null, music: null })).toBe('')
  })

  it('shows what went wrong when the library cannot be reached', async () => {
    vi.spyOn(gamApi, 'search').mockRejectedValue(
      new Error('Could not reach the asset library')
    )
    render(
      <FootageSearch
        title="F"
        purpose="scene"
        initialQuery="x"
        onPick={vi.fn()}
        onClose={vi.fn()}
      />
    )
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not reach the asset library'
    )
  })
})

describe('FootageSearch: a sound’s moment', () => {
  async function pick(hit: GamHit) {
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([hit]))
    // Resolved, so the waveform knows its length and can place the shading.
    vi.spyOn(gamApi, 'peaks').mockResolvedValue({ duration: 120, peaks: [1] })
    render(
      <FootageSearch title="Music" purpose="track" onPick={vi.fn()} onClose={vi.fn()} />
    )
    await userEvent.type(screen.getByLabelText('Search the asset library'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Search' }))
    await userEvent.click(await screen.findByRole('button', { name: /Voice memo/ }))
  }

  const memo = asset({
    id: 'v1',
    name: 'Voice memo',
    asset_type: 'audio',
    duration_seconds: 120,
    thumb_url: null,
  })

  it('shows the line that matched on the waveform', async () => {
    await pick({ asset: memo, score: 1, snippet: '', start_time: 12, end_time: 18 })

    expect(await screen.findAllByTestId('outside-moment')).toHaveLength(2)
    expect(screen.getByText('2:00 long · matched at 0:11–0:18')).toBeInTheDocument()
  })

  it('shows a GAM clip’s own window when nothing was said', async () => {
    const clip = { ...memo, parent_asset_id: 'p1', in_point: 30, out_point: 90 }
    await pick({ asset: clip, score: 1, snippet: '', start_time: null, end_time: null })

    expect(await screen.findAllByTestId('outside-moment')).toHaveLength(2)
    expect(screen.getByText('2:00 long · clip of 0:30–1:30')).toBeInTheDocument()
  })

  it('shades nothing for a hit on the name of a whole file', async () => {
    await pick({ asset: memo, score: 1, snippet: '', start_time: null, end_time: null })

    expect(await screen.findByText('2:00 long')).toBeInTheDocument()
    expect(screen.queryByTestId('outside-moment')).not.toBeInTheDocument()
  })
})
