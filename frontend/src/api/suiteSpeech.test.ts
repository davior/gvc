import { describe, expect, it } from 'vitest'
import { streamUrl } from '@/api/suiteSpeech'

describe('streamUrl', () => {
  it('is the suite as a websocket, naming GVC and carrying a token when there is one', () => {
    expect(streamUrl('https://suite.example.test', 'a b')).toBe(
      'wss://suite.example.test/api/v1/ai/speech/stt/stream?app=gvc&token=a+b'
    )
    // No token (GVC normally has none): the shared cookie signs the stream in.
    expect(streamUrl('https://suite.example.test', null)).toBe(
      'wss://suite.example.test/api/v1/ai/speech/stt/stream?app=gvc'
    )
    expect(streamUrl('http://localhost:8003', 't')).toMatch(/^ws:\/\/localhost:8003\//)
  })
})
