import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/config', () => ({
  loadConfig: () =>
    Promise.resolve({
      ai_backend: 'suite',
      suite_base_url: 'https://suite.example.test',
    }),
  currentConfig: () => ({
    ai_backend: 'suite',
    suite_base_url: 'https://suite.example.test',
  }),
}))

afterEach(() => vi.restoreAllMocks())

async function readiness(outcome: () => Promise<unknown>) {
  vi.resetModules()
  const create = axios.create
  vi.spyOn(axios, 'create').mockImplementation((...args) => {
    const instance = create(...args)
    instance.get = outcome as never
    return instance
  })
  const { suiteSpeechApi } = await import('@/api/suiteSpeech')
  return suiteSpeechApi.ready()
}

const failed = (status?: number) =>
  Object.assign(new Error('x'), {
    isAxiosError: true,
    response: status ? { status } : undefined,
  })

describe('whether dictation can be offered, and why not', () => {
  it('is ready when the suite has a Deepgram key', async () => {
    expect(
      await readiness(() => Promise.resolve({ data: { data: { ready: true } } }))
    ).toEqual({ state: 'ready' })
  })

  it('names the missing key', async () => {
    const r = await readiness(() => Promise.resolve({ data: { data: { ready: false } } }))
    expect(r).toMatchObject({
      state: 'unavailable',
      reason: expect.stringContaining('No Deepgram key'),
    })
  })

  it('names CORS_ORIGIN when the browser could not make the request', async () => {
    const r = await readiness(() => Promise.reject(failed()))
    expect(r).toMatchObject({
      state: 'unavailable',
      reason: expect.stringContaining('CORS_ORIGIN'),
    })
  })

  it('says the session was refused on a 401', async () => {
    const r = await readiness(() => Promise.reject(failed(401)))
    expect(r).toMatchObject({
      state: 'unavailable',
      reason: expect.stringContaining('did not accept'),
    })
  })
})
