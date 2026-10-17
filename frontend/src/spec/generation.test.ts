import { describe, expect, it } from 'vitest'
import type { GenerationModel } from '@/api/generations'
import type { VideoSpec } from '@/api/projects'
import { gamIdsIn } from '@/spec/footage'
import {
  dollars,
  estimateCost,
  fillGenerated,
  latestByKey,
  unmadeGenerates,
} from '@/spec/generation'

const spec: VideoSpec = {
  title: 'T',
  assets: {
    a_dam: { from: 'generate', type: 'image', prompt: 'A dam', label: 'Dam' },
    a_song: { from: 'generate', type: 'music', prompt: 'Calm' },
  },
  segments: [],
}

const model = (over: Partial<GenerationModel>): GenerationModel => ({
  id: 'm',
  kind: 'image_to_video',
  label: 'M',
  note: '',
  price: '',
  unit_price: 0.07,
  price_unit: 'second',
  options: { durations: ['5', '10'] },
  ...over,
})

describe('generated assets in a spec', () => {
  it('fills a placeholder and keeps its prompt', () => {
    const next = fillGenerated(spec, 'a_dam', 'x1')
    expect(next.assets?.a_dam).toEqual({
      from: 'generate',
      type: 'image',
      prompt: 'A dam',
      label: 'Dam',
      status: 'ready',
      result: { from: 'gam', id: 'x1' },
    })
    expect(unmadeGenerates(next).map((p) => p.key)).toEqual(['a_song'])
    expect(gamIdsIn(next)).toEqual(['x1'])
    expect(fillGenerated(spec, 'a_nope', 'x1')).toBe(spec)
  })

  it('takes the latest generation of each placeholder', () => {
    const rows = [
      { id: '1', asset_key: 'a' },
      { id: '2', asset_key: 'b' },
      { id: '3', asset_key: 'a' },
    ] as Parameters<typeof latestByKey>[0]
    expect(latestByKey(rows).a.id).toBe('3')
  })

  it('estimates at list price where it can', () => {
    expect(estimateCost(model({}), 1, '10')).toBeCloseTo(0.7)
    expect(estimateCost(model({}), 1)).toBeCloseTo(0.35)
    expect(
      estimateCost(model({ price_unit: 'image', unit_price: 0.039 }), 3)
    ).toBeCloseTo(0.117)
    expect(estimateCost(model({ price_unit: 'megapixel' }), 1)).toBeNull()
    expect(dollars(0.006)).toBe('$0.006')
    expect(dollars(0.35)).toBe('$0.35')
  })
})
