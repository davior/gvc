import { describe, expect, it } from 'vitest'
import type { VideoSpec } from '@/api/projects'
import { setOutput, setVoice } from '@/spec/settings'

const blank: VideoSpec = { title: 'T', segments: [] }

describe('setOutput', () => {
  it('writes only what differs from the default, and removes the section when empty', () => {
    const vertical = setOutput(blank, { aspect: '9:16', fps: 30 })
    expect(vertical.output).toEqual({ aspect: '9:16' })
    expect(setOutput(vertical, { aspect: '16:9' }).output).toBeUndefined()
  })

  it('keeps fields it was not asked about, such as ones a newer spec added', () => {
    const spec = { ...blank, output: { quality: 'high', future: 1 } } as VideoSpec
    expect(setOutput(spec, { chapters: false }).output).toEqual({
      quality: 'high',
      future: 1,
      chapters: false,
    })
  })
})

describe('setVoice', () => {
  it('pins a named voice and clears it when blanked', () => {
    const named = setVoice(blank, { voice: '  Rachel ' })
    expect(named.voice).toEqual({ voice: 'Rachel' })
    expect(setVoice(named, { voice: '' }).voice).toBeUndefined()
  })

  it('stores a pause only when it is not the default one, and speed 1 not at all', () => {
    const slow = setVoice(blank, { speed: 0.9, pauses: { heading_ms: 1200 } })
    expect(slow.voice).toEqual({ speed: 0.9, pauses: { heading_ms: 1200 } })
    const back = setVoice(setVoice(slow, { speed: 1 }), { pauses: { heading_ms: 800 } })
    expect(back.voice).toBeUndefined()
  })
})

import {
  patchSetting,
  setChromeBlock,
  setSceneChrome,
  STYLE_DEFAULTS,
} from '@/spec/settings'

describe('patchSetting', () => {
  it('writes only what differs, and removes every group left empty on the way up', () => {
    const big = patchSetting(
      blank,
      ['style', 'cards', 'title'],
      { title_pct: 9 },
      STYLE_DEFAULTS.cardText
    )
    expect(big.style).toEqual({ cards: { title: { title_pct: 9 } } })
    const back = patchSetting(
      big,
      ['style', 'cards', 'title'],
      { title_pct: 6.8 },
      STYLE_DEFAULTS.cardText
    )
    expect(back.style).toBeUndefined()
  })

  it('leaves sibling settings alone, and compares lists by value', () => {
    const spec = {
      ...blank,
      style: { fit: 'crop', background: { angle: 10 } },
    } as VideoSpec
    const next = patchSetting(
      spec,
      ['style', 'background'],
      { colors: ['#1e293b', '#0f172a'] },
      STYLE_DEFAULTS.background
    )
    expect(next.style).toEqual({ fit: 'crop', background: { angle: 10 } })
  })
})

describe('setChromeBlock', () => {
  it('keeps a block that equals the defaults, since present means on', () => {
    const on = setChromeBlock(blank, 'watermark', {})
    expect(on.chrome).toEqual({ watermark: {} })
    expect(setChromeBlock(on, 'watermark', null).chrome).toBeUndefined()
  })
})

describe('setSceneChrome', () => {
  it('sets a scene on or off, and back to the default by removing the field', () => {
    const spec: VideoSpec = { title: 'T', segments: [{ id: 'a', kind: 'scene' }] }
    const off = setSceneChrome(spec, 0, false)
    expect(off.segments[0].chrome).toBe(false)
    expect('chrome' in setSceneChrome(off, 0, undefined).segments[0]).toBe(false)
  })
})
