import { describe, expect, it } from 'vitest'
import type { GamAsset, GamHit } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import {
  assetKeyFor,
  clock,
  gamIdsIn,
  momentTrim,
  placeHit,
  removeVisual,
  resolveSearch,
  unresolvedSearches,
} from '@/spec/footage'

function asset(overrides: Partial<GamAsset> = {}): GamAsset {
  return {
    id: 'g1',
    name: 'Archive interview, 1971.mp4',
    asset_type: 'video',
    duration_seconds: 1800,
    width: 1920,
    height: 1080,
    file_url: 'https://gam.test/media/g1',
    thumb_url: 'https://gam.test/media/g1.jpg',
    credit: '',
    parent_asset_id: null,
    in_point: null,
    out_point: null,
    missing: false,
    ...overrides,
  }
}

function hit(overrides: Partial<GamHit> = {}, a: Partial<GamAsset> = {}): GamHit {
  return {
    asset: asset(a),
    score: 0.03,
    snippet: 'the «salt» road',
    start_time: 734,
    end_time: 741.5,
    ...overrides,
  }
}

function spec(): VideoSpec {
  return {
    title: 'T',
    segments: [
      {
        id: 's_1',
        kind: 'scene',
        visual: { asset: 'a_old', fit: 'pad', motion: { effect: 'zoom_in' } },
        narration: { beats: [{ id: 'b1', text: 'Words.' }] },
        overlays: [{ id: 'o1', type: 'text', text: 'x' }],
      },
    ],
  }
}

describe('momentTrim', () => {
  it('pads what was said so a cut does not clip a word', () => {
    expect(momentTrim(hit())).toEqual({ in: 733.5, out: 742 })
  })

  it('assumes a short moment when GAM does not say where it ends', () => {
    expect(momentTrim(hit({ end_time: null }))).toEqual({ in: 733.5, out: 739.5 })
  })

  it('widens to a minimum around the middle of the line', () => {
    expect(momentTrim(hit(), { min: 20 })).toEqual({ in: 727.8, out: 747.8 })
  })

  it('cuts to a maximum', () => {
    expect(momentTrim(hit(), { max: 4 })).toEqual({ in: 733.5, out: 737.5 })
  })

  it('stays inside the asset at both ends', () => {
    expect(momentTrim(hit({ start_time: 1, end_time: 2 }), { min: 10 })).toEqual({
      in: 0,
      out: 10,
    })
    expect(momentTrim(hit({ start_time: 1797, end_time: 1800 }))).toEqual({
      in: 1796.5,
      out: 1800,
    })
  })

  it('has nothing to cut for a hit on the file rather than a moment', () => {
    expect(momentTrim(hit({ start_time: null, end_time: null }))).toBeUndefined()
  })
})

describe('assetKeyFor', () => {
  it('makes a readable key and keeps it unique', () => {
    const s = {
      ...spec(),
      assets: { a_archive_interview_1971: { from: 'gam' as const, id: 'other' } },
    }
    expect(assetKeyFor(s, asset())).toBe('a_archive_interview_1971_2')
  })

  it('reuses the key already used for the same asset', () => {
    const s = { ...spec(), assets: { a_reel: { from: 'gam' as const, id: 'g1' } } }
    expect(assetKeyFor(s, asset())).toBe('a_reel')
  })
})

describe('placeHit', () => {
  it('puts a moment under the narration as muted b-roll', () => {
    const next = placeHit(spec(), 0, hit(), 'broll')
    const scene = next.segments[0]
    expect(scene.kind).toBe('scene')
    expect(scene.visual).toEqual({
      asset: 'a_archive_interview_1971',
      fit: 'pad',
      trim: { in: 733.5, out: 742 },
      audio: 'mute',
      loop: true,
    })
    expect(scene.narration?.beats[0].text).toBe('Words.')
    expect(scene.overlays).toHaveLength(1)
    expect(next.assets?.a_archive_interview_1971).toEqual({
      from: 'gam',
      id: 'g1',
      type: 'video',
      label: 'Archive interview, 1971.mp4',
    })
  })

  it('makes a clip that plays its own sound and carries nothing said over it', () => {
    const clip = placeHit(spec(), 0, hit(), 'clip').segments[0]
    expect(clip.kind).toBe('clip')
    expect(clip.visual?.audio).toBe('play')
    expect(clip.visual?.loop).toBe(false)
    expect(clip.narration).toBeUndefined()
    expect(clip.overlays).toBeUndefined()
  })

  it('takes a picture whole, with no trim', () => {
    const visual = placeHit(
      spec(),
      0,
      hit({}, { asset_type: 'image', id: 'i1', name: 'Map' }),
      'broll'
    ).segments[0].visual
    expect(visual?.trim).toBeUndefined()
    expect(visual?.asset).toBe('a_map')
  })

  it('turns a clip whose footage is removed back into a scene', () => {
    const clip = placeHit(spec(), 0, hit(), 'clip')
    const scene = removeVisual(clip, 0).segments[0]
    expect(scene.kind).toBe('scene')
    expect(scene.visual).toBeUndefined()
    expect(scene.narration?.beats).toEqual([{ id: 'b1', text: '' }])
  })

  it('removes a picture and keeps the rest of the scene', () => {
    const scene = removeVisual(spec(), 0).segments[0]
    expect(scene.visual).toBeUndefined()
    expect(scene.narration?.beats[0].text).toBe('Words.')
  })
})

describe('search placeholders', () => {
  function withPlaceholder(): VideoSpec {
    return {
      title: 'T',
      assets: {
        a_ruins: {
          from: 'search',
          query: 'drone footage of ruins',
          moment: { min: 12 },
          status: 'unresolved',
        },
        a_map: { from: 'gam', id: 'm1' },
      },
      segments: [
        { id: 's_1', kind: 'scene', visual: { asset: 'a_ruins' } },
        { id: 's_2', kind: 'scene', visual: { asset: 'a_ruins', audio: 'mute' } },
        { id: 's_3', kind: 'scene', visual: { asset: 'a_map' } },
      ],
    }
  }

  it('lists what is still to find', () => {
    expect(unresolvedSearches(withPlaceholder()).map((p) => p.key)).toEqual(['a_ruins'])
  })

  it('resolves to the found moment and trims every scene that shows it', () => {
    const next = resolveSearch(withPlaceholder(), 'a_ruins', hit())
    expect(next.assets?.a_ruins).toMatchObject({
      from: 'search',
      query: 'drone footage of ruins',
      status: 'resolved',
      type: 'video',
      result: { from: 'gam', id: 'g1', in: 731.8, out: 743.8 },
    })
    expect(next.segments[0].visual?.trim).toEqual({ in: 731.8, out: 743.8 })
    expect(next.segments[1].visual).toEqual({
      asset: 'a_ruins',
      audio: 'mute',
      trim: { in: 731.8, out: 743.8 },
    })
    expect(next.segments[2].visual?.trim).toBeUndefined()
    expect(unresolvedSearches(next)).toEqual([])
    expect(gamIdsIn(next)).toEqual(['g1', 'm1'])
  })
})

describe('clock', () => {
  it('reads like a timecode', () => {
    expect(clock(734.2)).toBe('12:14')
    expect(clock(3725)).toBe('1:02:05')
    expect(clock(5)).toBe('0:05')
  })
})
