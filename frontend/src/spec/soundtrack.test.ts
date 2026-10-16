import { describe, expect, it } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import { clampFrame, setMotion, setTransition } from '@/spec/scene'
import {
  addTrack,
  crossfadeInto,
  describeAnchor,
  removeTrack,
  updateTrack,
} from '@/spec/soundtrack'

const song = (id: string, name: string): GamAsset => ({
  id,
  name,
  asset_type: 'audio',
  duration_seconds: 180,
  width: null,
  height: null,
  file_url: null,
  thumb_url: null,
  credit: '',
  parent_asset_id: null,
  in_point: null,
  out_point: null,
  missing: false,
})

function spec(): VideoSpec {
  return {
    title: 'T',
    assets: { a_map: { from: 'gam', id: 'p' } },
    segments: [
      { id: 's1', kind: 'scene', visual: { asset: 'a_map' } },
      { id: 's2', kind: 'scene' },
      { id: 's3', kind: 'scene' },
    ],
  }
}

describe('soundtrack', () => {
  it('adds a music track between two scenes, with a readable key and gentle defaults', () => {
    const next = addTrack(spec(), song('g1', 'Desert Theme.mp3'), 'music', 's1', 's2')
    expect(next.assets?.a_desert_theme).toEqual({
      from: 'gam',
      id: 'g1',
      type: 'audio',
      label: 'Desert Theme.mp3',
    })
    expect(next.audio_tracks).toEqual([
      {
        id: 'm_1',
        kind: 'music',
        asset: 'a_desert_theme',
        start: { segment: 's1', edge: 'start' },
        end: { segment: 's2', edge: 'end' },
        volume: 0.18,
        fade_in: 1.5,
        fade_out: 3,
      },
    ])
  })

  it('changes the soundtrack partway: a second track, crossfaded from the first', () => {
    let next = addTrack(spec(), song('g1', 'Theme'), 'music', 's1', 's3')
    next = addTrack(next, song('g2', 'Close'), 'music', 's3')
    next = crossfadeInto(next, 1, 3)
    const [first, second] = next.audio_tracks!
    // The first now stops where the third scene starts, fading over the last 3 s ...
    expect(first.end).toEqual({ segment: 's3', edge: 'start' })
    expect(first.fade_out).toBe(3)
    // ... and the second starts 3 s before it, fading in over those same 3 s.
    expect(second.start).toEqual({ segment: 's3', edge: 'start', offset: -3 })
    expect(second.fade_in).toBe(3)
    // No end: it plays to its own end.
    expect(second.end).toBeUndefined()
  })

  it('edits and removes a track, an undefined field meaning "not set"', () => {
    let next = addTrack(spec(), song('g1', 'Theme'), 'music', 's1', 's2')
    next = updateTrack(next, 0, { volume: 0.4, end: undefined })
    expect(next.audio_tracks![0].volume).toBe(0.4)
    expect('end' in next.audio_tracks![0]).toBe(false)
    expect(removeTrack(next, 0).audio_tracks).toEqual([])
  })

  it('describes an anchor in words', () => {
    const labels = { s3: 'The market' }
    expect(describeAnchor({ segment: 's3', edge: 'start', offset: -3 }, labels)).toBe(
      'start of The market −3 s'
    )
    expect(describeAnchor(undefined, labels)).toBe('its own end')
    expect(describeAnchor('video_end', labels)).toBe('the end of the video')
  })
})

describe('scene settings', () => {
  it('overrides the transition into a scene, and "project default" removes it', () => {
    const dissolved = setTransition(spec(), 1, { style: 'dissolve' })
    expect(dissolved.segments[1].transition_in).toEqual({ style: 'dissolve' })
    expect('transition_in' in setTransition(dissolved, 1, undefined).segments[1]).toBe(
      false
    )
  })

  it('sets a Ken Burns path on a scene with a picture, and only there', () => {
    const path = {
      effect: 'path',
      from: { x: 0, y: 0, w: 1 },
      to: { x: 0.5, y: 0.4, w: 0.4 },
    }
    expect(setMotion(spec(), 0, path).segments[0].visual?.motion).toEqual(path)
    expect(setMotion(spec(), 1, path).segments[1].visual).toBeUndefined()
  })

  it('keeps a frame inside the picture', () => {
    // A 16:9 frame on a 16:9 picture is as tall as it is a fraction of the width.
    expect(clampFrame({ x: 0.8, y: 0.9, w: 0.5 }, 1)).toEqual({ x: 0.5, y: 0.5, w: 0.5 })
    expect(clampFrame({ x: -1, y: 0, w: 3 }, 1)).toEqual({ x: 0, y: 0, w: 1 })
  })
})
