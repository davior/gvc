import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import { blobError, formatPath, scriptFilename, specIssuesOf } from '@/api/projects'

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

describe('script export helpers', () => {
  it('prefers the UTF-8 file name and falls back to the plain one', () => {
    expect(
      scriptFilename(
        `attachment; filename="Caf-script.docx"; filename*=UTF-8''Caf%C3%A9-script.docx`
      )
    ).toBe('Café-script.docx')
    expect(scriptFilename('attachment; filename="Plain-script.docx"')).toBe(
      'Plain-script.docx'
    )
    expect(scriptFilename(undefined)).toBeNull()
  })

  it('reads a JSON error out of a blob response', async () => {
    const error = {
      response: {
        data: new Blob([
          JSON.stringify({ detail: { code: 'invalid_spec', message: 'Nope' } }),
        ]),
      },
    }
    const parsed = (await blobError(error)) as typeof error
    expect(parsed.response.data).toEqual({
      detail: { code: 'invalid_spec', message: 'Nope' },
    })
  })
})
