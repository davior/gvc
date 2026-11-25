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
import { webApi, type WebImage } from '@/api/web'

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

  describe('pictures from the web', () => {
    const river: WebImage = {
      image_url: 'https://img.test/river.jpg',
      page_url: 'https://example.test/river',
      title: 'Dry riverbed',
      thumbnail_url: 'https://img.test/river_t.jpg',
      width: 1920,
      height: 1080,
      description: 'A cracked riverbed at noon',
    }
    const filed = asset({ id: 'gam-web-1', name: 'Dry riverbed', asset_type: 'image' })

    it('searches the web, files the chosen picture in GAM and hands it back as a hit', async () => {
      const images = vi.spyOn(webApi, 'images').mockResolvedValue([river])
      const importImage = vi.spyOn(gamApi, 'importImage').mockResolvedValue(filed)
      const library = vi.spyOn(gamApi, 'search')
      const onPick = vi.fn()
      render(
        <FootageSearch
          title="Background"
          purpose="picture"
          initialType="image"
          projectId="p1"
          onPick={onPick}
          onClose={vi.fn()}
        />
      )

      await userEvent.type(screen.getByLabelText('Search the asset library'), 'riverbed')
      await userEvent.click(screen.getByRole('button', { name: /Web pictures/ }))
      expect(images).toHaveBeenCalledWith('riverbed', 'p1')
      expect(library).not.toHaveBeenCalled()

      await userEvent.click(await screen.findByRole('button', { name: 'Dry riverbed' }))
      expect(screen.getByText(/Who may use this picture is unknown/)).toBeInTheDocument()
      expect(screen.getByRole('link', { name: /Source page/ })).toHaveAttribute(
        'href',
        'https://example.test/river'
      )
      await userEvent.click(screen.getByRole('button', { name: 'Use this picture' }))

      expect(importImage).toHaveBeenCalledWith(river)
      expect(onPick).toHaveBeenCalledWith(
        { asset: filed, score: 0, snippet: '', start_time: null, end_time: null },
        'broll'
      )
    })

    it('opens on a placeholder’s shortlist without searching again', async () => {
      const images = vi.spyOn(webApi, 'images')
      render(
        <FootageSearch
          title="Find"
          purpose="resolve"
          initialQuery="a dry riverbed"
          initialType="image"
          candidates={[river]}
          onPick={vi.fn()}
          onClose={vi.fn()}
        />
      )
      expect(screen.getByRole('button', { name: /Web pictures/ })).toHaveAttribute(
        'aria-pressed',
        'true'
      )
      expect(screen.getByRole('button', { name: 'Dry riverbed' })).toBeInTheDocument()
      expect(images).not.toHaveBeenCalled()
    })

    it('says what went wrong when GAM will not take the picture', async () => {
      vi.spyOn(webApi, 'images').mockResolvedValue([river])
      vi.spyOn(gamApi, 'importImage').mockRejectedValue(
        Object.assign(new Error('x'), {
          isAxiosError: true,
          response: {
            status: 400,
            data: {
              detail: {
                code: 'image_unavailable',
                message: 'That link is not a picture GAM can store',
              },
            },
          },
        })
      )
      const onPick = vi.fn()
      render(
        <FootageSearch
          title="Overlay"
          purpose="overlay"
          candidates={[river]}
          onPick={onPick}
          onClose={vi.fn()}
        />
      )
      await userEvent.click(screen.getByRole('button', { name: 'Dry riverbed' }))
      await userEvent.click(screen.getByRole('button', { name: 'Put on screen' }))
      expect(await screen.findByRole('alert')).toHaveTextContent(
        'That link is not a picture GAM can store'
      )
      expect(onPick).not.toHaveBeenCalled()
    })

    it('is not offered for a sound', () => {
      render(
        <FootageSearch title="Music" purpose="track" onPick={vi.fn()} onClose={vi.fn()} />
      )
      expect(
        screen.queryByRole('button', { name: /Web pictures/ })
      ).not.toBeInTheDocument()
    })
  })
})

describe('FootageSearch: GAM playlists', () => {
  const crisis = {
    id: 'p1',
    name: 'The financial crisis',
    description: 'Everyone on 2008.',
    item_count: 2,
    total_seconds: 42.5,
    thumb_url: null,
    updated_at: null,
  }
  const item = (id: string, overrides: Record<string, unknown> = {}) => ({
    id,
    asset_id: 'g1',
    asset_name: 'Archive interview',
    asset_type: 'video',
    in_point: 62,
    out_point: 101.5,
    start: 62,
    end: 101.5,
    image_seconds: null,
    label: 'On the bailout',
    note: null,
    asset_duration_seconds: 1800,
    width: null,
    height: null,
    file_url: 'https://gam.test/media/g1?sig=x',
    thumb_url: null,
    missing: false,
    ...overrides,
  })
  const detail = {
    ...crisis,
    items: [
      item('it-1'),
      item('it-2', {
        asset_id: 'i1',
        asset_name: 'Map',
        asset_type: 'image',
        in_point: null,
        out_point: null,
        start: 0,
        end: 3,
        image_seconds: 3,
        label: null,
        asset_duration_seconds: null,
      }),
    ],
  }

  it('searches playlists by name, goes through the items in order and uses one as it is cut', async () => {
    const list = vi.spyOn(gamApi, 'playlists').mockResolvedValue([crisis])
    vi.spyOn(gamApi, 'playlist').mockResolvedValue(detail)
    const onPick = vi.fn()
    render(
      <FootageSearch title="Footage" purpose="scene" onPick={onPick} onClose={vi.fn()} />
    )

    await userEvent.click(screen.getByRole('button', { name: /Playlists/ }))
    await userEvent.type(
      await screen.findByLabelText('Search playlists'),
      'crisis{Enter}'
    )
    expect(list).toHaveBeenLastCalledWith('crisis')
    await userEvent.click(
      await screen.findByRole('button', { name: /The financial crisis/ })
    )

    const items = await screen.findByLabelText('Items of The financial crisis')
    expect(items).toHaveTextContent(/1.*On the bailout.*1:02–1:41.*2.*Map.*3 s/)
    await userEvent.click(screen.getByRole('button', { name: /^1 On the bailout/ }))
    // The item's own range, not padded as a search hit's moment would be.
    expect(screen.getByText('Uses 1:02–1:41 (40 s)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Use as b-roll' }))
    const [hit] = onPick.mock.calls[0]
    expect([hit.start_time, hit.end_time, hit.exact]).toEqual([62, 101.5, true])
  })

  it('takes an item out of the playlist', async () => {
    vi.spyOn(gamApi, 'playlists').mockResolvedValue([crisis])
    vi.spyOn(gamApi, 'playlist').mockResolvedValue(detail)
    const remove = vi
      .spyOn(gamApi, 'removePlaylistItem')
      .mockResolvedValue({ ...detail, items: detail.items.slice(1) })
    render(
      <FootageSearch title="Footage" purpose="scene" onPick={vi.fn()} onClose={vi.fn()} />
    )

    await userEvent.click(screen.getByRole('button', { name: /Playlists/ }))
    await userEvent.click(
      await screen.findByRole('button', { name: /The financial crisis/ })
    )
    await userEvent.click(
      await screen.findByRole('button', {
        name: 'Remove On the bailout from the playlist',
      })
    )
    expect(remove).toHaveBeenCalledWith('p1', 'it-1')
    expect(screen.queryByText('On the bailout')).toBeNull()
  })

  it('adds the selected moment to a playlist, or to a new one', async () => {
    vi.spyOn(gamApi, 'search').mockResolvedValue(result([spoken]))
    vi.spyOn(gamApi, 'playlists').mockResolvedValue([crisis])
    const add = vi.spyOn(gamApi, 'addPlaylistItems').mockResolvedValue(detail)
    const create = vi
      .spyOn(gamApi, 'createPlaylist')
      .mockResolvedValue({ ...detail, id: 'p2', name: 'Water' })
    render(
      <FootageSearch title="Footage" purpose="scene" onPick={vi.fn()} onClose={vi.fn()} />
    )

    await userEvent.type(
      screen.getByLabelText('Search the asset library'),
      'water{Enter}'
    )
    await userEvent.click(
      await screen.findByRole('button', { name: /Archive interview/ })
    )
    await userEvent.click(screen.getByRole('button', { name: 'Add to a GAM playlist' }))
    const group = await screen.findByRole('group', { name: 'Add to a GAM playlist' })
    expect(group).toHaveTextContent('Adds 12:13–12:22.')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(add).toHaveBeenCalledWith('p1', [
      { asset_id: 'g1', in_point: 733.5, out_point: 742 },
    ])
    expect(await screen.findByText('Added to The financial crisis.')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Playlist'), 'New playlist…')
    await userEvent.type(screen.getByLabelText("New playlist's name"), 'Water')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(create).toHaveBeenCalledWith({
      name: 'Water',
      items: [{ asset_id: 'g1', in_point: 733.5, out_point: 742 }],
    })
    expect(await screen.findByText('Added to Water.')).toBeInTheDocument()
  })
})
