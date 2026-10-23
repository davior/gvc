import { describe, expect, it } from 'vitest'
import type { GamAsset } from '@/api/gam'
import type { VideoSpec } from '@/api/projects'
import {
  footageOf,
  nudge,
  playWindow,
  setLength,
  setLoop,
  setTrim,
  setVolume,
  timingNote,
  trimAt,
} from '@/spec/clip'

const reel: GamAsset = {
  id: 'g1',
  name: 'Interview',
  asset_type: 'video',
  duration_seconds: 60,
  width: null,
  height: null,
  file_url: 'https://gam.test/f',
  thumb_url: null,
  credit: '',
  parent_asset_id: null,
  in_point: null,
  out_point: null,
  missing: false,
}

const clipOfParent: GamAsset = {
  ...reel,
  id: 'g2',
  parent_asset_id: 'g1',
  in_point: 20,
  out_point: 30,
}

function spec(visual: object, extra: object = {}): VideoSpec {
  return {
    title: 'T',
    assets: { v: { from: 'gam', id: 'g1' } },
    segments: [
      {
        id: 's1',
        kind: 'scene',
        visual: { asset: 'v', ...visual },
        narration: { beats: [{ id: 'b1', text: 'x'.repeat(150) }] },
        ...extra,
      },
      { id: 's2', kind: 'scene' },
    ],
  }
}

describe('trims', () => {
  it('nudges one end and keeps it inside the asset', () => {
    expect(nudge({ in: 2, out: 8 }, 'in', -1, 60)).toEqual({ in: 1, out: 8 })
    expect(nudge({ in: 0.5, out: 8 }, 'in', -1, 60)).toEqual({ in: 0, out: 8 })
    expect(nudge({ in: 2, out: 59.5 }, 'out', 1, 60)).toEqual({ in: 2, out: 60 })
  })

  it('never lets the two ends cross', () => {
    expect(nudge({ in: 2, out: 2.5 }, 'in', 1, 60)).toEqual({ in: 2.4, out: 2.5 })
    expect(trimAt({ in: 5, out: 8 }, 'out', 3, 60)).toEqual({ in: 5, out: 5.1 })
  })

  it('starts an untrimmed clip from the whole asset', () => {
    expect(nudge(undefined, 'out', -1, 60)).toEqual({ in: 0, out: 59 })
  })

  it('removes the trim to play the whole clip', () => {
    const next = setTrim(spec({ trim: { in: 1, out: 4 } }), 0, undefined)
    expect(next.segments[0].visual).toEqual({ asset: 'v' })
  })

  it('plays a GAM clip from its place in its parent’s file', () => {
    expect(playWindow(clipOfParent, { in: 1, out: 4 })).toEqual({ start: 21, end: 24 })
    expect(playWindow(clipOfParent)).toEqual({ start: 20, end: 30 })
    expect(playWindow(reel, { in: 5 })).toEqual({ start: 5, end: 60 })
  })
})

describe('scene length and looping', () => {
  it('writes and removes a fixed length, dropping an empty duration', () => {
    const fixed = setLength(spec({}), 0, 6.04)
    expect(fixed.segments[0].duration).toEqual({ fixed: 6 })
    expect('duration' in setLength(fixed, 0, undefined).segments[0]).toBe(false)
    const floored = setLength(spec({}, { duration: { min: 3 } }), 0, undefined)
    expect(floored.segments[0].duration).toEqual({ min: 3 })
  })

  it('sets whether short footage loops', () => {
    expect(setLoop(spec({}), 0, false).segments[0].visual?.loop).toBe(false)
  })

  it('sets a clip level, and drops it at the matched level', () => {
    const louder = setVolume(spec({ audio: 'play' }), 0, 4)
    expect(louder.segments[0].visual?.volume_db).toBe(4)
    expect('volume_db' in (setVolume(louder, 0, 0).segments[0].visual ?? {})).toBe(false)
  })
})

describe('timingNote', () => {
  it('says when footage is shorter than its narration and loops or holds', () => {
    // 150 characters at 15 a second, plus the scene's end pause: about 10.6 s.
    expect(timingNote(spec({ trim: { in: 0, out: 4 } }), 0, reel)).toBe(
      'Footage is 4 s; the scene runs about 10.6 s, so it loops.'
    )
    expect(timingNote(spec({ trim: { in: 0, out: 4 }, loop: false }), 0, reel)).toBe(
      'Footage is 4 s; the scene runs about 10.6 s, so it holds its last frame for 6.6 s.'
    )
  })

  it('says when footage runs longer than a fixed scene', () => {
    const fixed = spec({ trim: { in: 0, out: 12 } }, { duration: { fixed: 8 } })
    expect(timingNote(fixed, 0, reel)).toBe(
      'Footage is 12 s; the scene runs 8 s, so its last 4 s aren’t shown.'
    )
  })

  it('says nothing when they match', () => {
    const fixed = spec({ trim: { in: 0, out: 8 } }, { duration: { fixed: 8 } })
    expect(timingNote(fixed, 0, reel)).toBeNull()
  })

  it('names a blend out of a clip', () => {
    const s: VideoSpec = {
      ...spec({}),
      segments: [
        { id: 'c', kind: 'clip', visual: { asset: 'v', audio: 'play' } },
        { id: 'n', kind: 'scene', transition_in: { style: 'dissolve' } },
      ],
    }
    expect(timingNote(s, 0, reel)).toBe(
      'The dissolve into the next scene plays up to 0.6 s past the out point.'
    )
  })
})

describe('footageOf', () => {
  it('finds a generated clip’s asset and ignores a missing file', () => {
    const s: VideoSpec = {
      ...spec({}),
      assets: {
        v: {
          from: 'generate',
          type: 'video',
          prompt: 'p',
          result: { from: 'gam', id: 'g1' },
        },
      },
    } as VideoSpec
    expect(footageOf(s, s.segments[0], { g1: reel })?.id).toBe('g1')
    expect(footageOf(s, s.segments[0], { g1: { ...reel, missing: true } })).toBeNull()
  })
})
