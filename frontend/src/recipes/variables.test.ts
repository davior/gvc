import { describe, expect, it } from 'vitest'
import { inputsOf, placeholders, render } from '@/recipes/variables'

// The same cases as the backend's test_recipes.py, so the two readings cannot drift.
describe('recipe placeholders', () => {
  const prompt =
    '{{Topic}} and {{topic}} for {{target_audience}} on {{date}} in {{ Title }}'

  it('match loosely, keep the first spelling, and leave the built-ins out of the inputs', () => {
    expect(placeholders(prompt)).toEqual(['Topic', 'target_audience', 'date', 'Title'])
    expect(inputsOf(prompt)).toEqual(['Topic', 'target_audience'])
  })

  it('fill what has a value and leave the rest as typed', () => {
    expect(render(prompt, { topic: 'rivers', 'Target Audience': 'kids', date: '' })).toBe(
      'rivers and rivers for kids on {{date}} in {{ Title }}'
    )
  })
})
