import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as configModule from '@/api/config'
import { providersApi } from '@/api/providers'
import { themesApi } from '@/api/themes'
import { usageApi } from '@/api/usage'
import SettingsView from '@/views/SettingsView'

function serve(aiBackend: 'local' | 'suite') {
  vi.spyOn(configModule, 'loadConfig').mockResolvedValue({
    sign_in_url: 'https://suite.example.test',
    ai_backend: aiBackend,
    suite_base_url: 'https://suite.example.test/',
  })
}

beforeEach(() => {
  vi.spyOn(providersApi, 'list').mockResolvedValue([])
  vi.spyOn(themesApi, 'list').mockResolvedValue([])
  vi.spyOn(usageApi, 'summary').mockResolvedValue({
    totals: {
      total_events: 0,
      priced_events: 0,
      cost: 0,
      currency: 'USD',
      estimated: true,
      tokens: 0,
    },
    by_provider: [],
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('SettingsView', () => {
  it('shows the app’s own provider form while the assistant uses its own provider', async () => {
    serve('local')
    render(<SettingsView />)
    expect(await screen.findByText(/no provider configured yet/i)).toBeInTheDocument()
    expect(screen.queryByText(/managed in gecko suite/i)).toBeNull()
  })

  it('says AI lives in Gecko Suite, with links there, once the assistant uses it', async () => {
    serve('suite')
    render(<SettingsView />)
    expect(await screen.findByText(/managed in gecko suite/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /providers/i })).toHaveAttribute(
      'href',
      'https://suite.example.test/providers'
    )
    expect(screen.getByRole('link', { name: /usage/i })).toHaveAttribute(
      'href',
      'https://suite.example.test/usage'
    )
    // A form whose provider is never called would be wrong, not just redundant.
    expect(screen.queryByText(/no provider configured yet/i)).toBeNull()
  })
})
