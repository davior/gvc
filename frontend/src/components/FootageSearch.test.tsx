import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
