import { describe, expect, it } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import { anchorFrom, anchorValue } from '@/spec/anchors'
import {
  addImageOverlay,
  addOverlay,
  newOverlayId,
  removeOverlay,
  setCredits,
  updateOverlay,
} from '@/spec/overlays'

const spec: VideoSpec = {
  title: 'T',
  segments: [
    { id: 's1', kind: 'scene', overlays: [{ id: 'o_1', type: 'quote', text: 'q' }] },
    { id: 's2', kind: 'scene' },
  ],
}

const logo = {
  id: 'g9',
  name: 'Logo',
  asset_type: 'image',
} as GamAsset

describe('overlays', () => {
  it('adds text and a lower third with ids unique across the spec', () => {
    const one = addOverlay(spec, 1, 'text')
    const two = addOverlay(one, 1, 'lower_third')
    expect(two.segments[1].overlays?.map((o) => [o.id, o.type])).toEqual([
      ['o_2', 'text'],
      ['o_3', 'lower_third'],
    ])
    expect(newOverlayId(two)).toBe('o_4')
    // The quote on s1 is left as it was.
    expect(two.segments[0]).toBe(spec.segments[0])
  })

  it('adds a picture once to the asset registry', () => {
    const one = addImageOverlay(spec, 1, logo)
    const two = addImageOverlay(one, 0, logo)
    expect(Object.keys(two.assets ?? {})).toEqual(['a_logo'])
    expect(two.segments[0].overlays?.[1]).toMatchObject({
      type: 'image',
      asset: 'a_logo',
    })
  })

  it('updates a field, removes one set back to undefined, and deletes', () => {
    let next = addOverlay(spec, 1, 'text')
    next = updateOverlay(next, 1, 'o_2', { size_pct: 12, fade: 1 })
    next = updateOverlay(next, 1, 'o_2', { fade: undefined })
    expect(next.segments[1].overlays?.[0]).not.toHaveProperty('fade')
    expect(next.segments[1].overlays?.[0]).toMatchObject({ size_pct: 12 })
    expect(removeOverlay(next, 1, 'o_2').segments[1].overlays).toEqual([])
  })

  it('turns credits on and off', () => {
    const on = setCredits(spec, { auto: true, extra: ['Narrated by Rex'] })
    expect(on.credits).toEqual({ auto: true, extra: ['Narrated by Rex'] })
    expect(setCredits(on, null)).not.toHaveProperty('credits')
  })
})

describe('anchor values', () => {
  it('round-trip a scene edge, a beat, the own scene and the video ends', () => {
    for (const value of ['video_start', 'start:s2', 'end:s1:b2', 'start:', 'end::b1']) {
      expect(anchorValue(anchorFrom(value))).toBe(value)
    }
    expect(anchorFrom('end::b1', 0.5)).toEqual({ beat: 'b1', edge: 'end', offset: 0.5 })
    expect(anchorFrom('start:')).toEqual({ edge: 'start' })
  })
})
