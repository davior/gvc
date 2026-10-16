import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import { formatPath, specIssuesOf } from '@/api/projects'

function rejection(detail: unknown, status = 422): AxiosError {
  const error = new AxiosError('failed')
  error.response = {
    data: { detail },
    status,
    statusText: '',
    headers: {},
    config: {} as never,
  }
  return error
}

describe('formatPath', () => {
  it('reads like a path into JSON', () => {
    expect(formatPath(['segments', 2, 'visual', 'motion', 'from', 'w'])).toBe(
      'segments[2].visual.motion.from.w'
    )
    expect(formatPath([])).toBe('(the whole spec)')
  })
})

describe('specIssuesOf', () => {
  it('pulls the issues out of an invalid_spec refusal', () => {
    const issues = [{ path: ['voice', 'speed'], message: 'too fast' }]
    expect(
      specIssuesOf(rejection({ code: 'invalid_spec', message: 'x', issues }))
    ).toEqual(issues)
  })

  it('finds none in any other failure', () => {
    expect(specIssuesOf(rejection({ code: 'not_found', message: 'gone' }, 404))).toEqual(
      []
    )
    expect(specIssuesOf(new Error('network'))).toEqual([])
  })
})
