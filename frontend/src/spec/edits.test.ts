import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import {
  addScene,
  moveSegment,
  narrationText,
  nextSegmentId,
  removeSegment,
  withNarrationText,
} from '@/spec/edits'

function spec(): VideoSpec {
  return {
    title: 'T',
    style: { transition: { style: 'fade' } },
    segments: [
      { id: 's_title', kind: 'card', card: { variant: 'title', title: 'T' } },
      {
        id: 's_1',
        kind: 'scene',
        visual: { asset: 'a_map' },
        narration: {
          beats: [
            { id: 'b1', text: 'One.' },
            { id: 'b2', text: 'Two.', kind: 'quote' },
          ],
        },
      },
    ],
  }
}

describe('scene edits', () => {
  it('adds a scene with a fresh id, never reusing one', () => {
    const s = spec()
    s.segments.push({ id: 's_2', kind: 'scene' })
    expect(nextSegmentId(s)).toBe('s_3')
    const next = addScene(s, 0)
    expect(next.segments.map((x) => x.id)).toEqual(['s_title', 's_3', 's_1', 's_2'])
    expect(next.segments[1].narration?.beats).toEqual([{ id: 'b1', text: '' }])
  })

  it('moves within bounds and leaves the spec alone at an edge', () => {
    const s = spec()
    expect(moveSegment(s, 1, -1).segments.map((x) => x.id)).toEqual(['s_1', 's_title'])
    expect(moveSegment(s, 0, -1)).toBe(s)
    expect(moveSegment(s, 1, 1)).toBe(s)
  })

  it('removes a segment and keeps every field it does not understand', () => {
    const next = removeSegment(spec(), 0)
    expect(next.segments.map((x) => x.id)).toEqual(['s_1'])
    expect(next.style).toEqual({ transition: { style: 'fade' } })
    expect(next.segments[0].visual).toEqual({ asset: 'a_map' })
  })
})

describe('narration as text', () => {
  it('reads beats as paragraphs', () => {
    expect(narrationText(spec().segments[1])).toBe('One.\n\nTwo.')
  })

  it('keeps each beat its id and its other fields when its words change', () => {
    const scene = withNarrationText(spec().segments[1], 'Uno.\n\nDos.')
    expect(scene.narration?.beats).toEqual([
      { id: 'b1', text: 'Uno.' },
      { id: 'b2', text: 'Dos.', kind: 'quote' },
    ])
    expect(scene.visual).toEqual({ asset: 'a_map' })
  })

  it('gives a new paragraph a new beat id', () => {
    const scene = withNarrationText(spec().segments[1], 'One.\n\nTwo.\n\nThree.')
    expect(scene.narration?.beats.map((b) => b.id)).toEqual(['b1', 'b2', 'b3'])
  })

  it('keeps a space typed at the end of a paragraph', () => {
    const scene = withNarrationText(spec().segments[1], 'One two ')
    expect(narrationText(scene)).toBe('One two ')
  })

  it('keeps one empty beat when the box is cleared', () => {
    const scene = withNarrationText(spec().segments[1], '')
    expect(scene.narration?.beats).toEqual([{ id: 'b1', text: '' }])
  })
})
