import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usageApi } from '@/api/usage'
import UsagePanel from '@/components/UsagePanel'

afterEach(() => vi.restoreAllMocks())

describe('UsagePanel', () => {
  it('says the total is an estimate, and a floor when some calls were not priced', async () => {
    vi.spyOn(usageApi, 'summary').mockResolvedValue({
      totals: {
        total_events: 3,
        priced_events: 2,
        cost: 0.0042,
        currency: 'USD',
        estimated: true,
        tokens: 12000,
      },
      by_provider: [
        {
          provider: 'anthropic',
          model: 'claude-opus-5-5',
          events: 2,
          units: 11000,
          cost: 0.0042,
        },
        { provider: 'custom', model: 'x', events: 1, units: 1000, cost: null },
      ],
    })
    render(<UsagePanel />)
    expect(await screen.findAllByText('$0.0042')).toHaveLength(2)
    expect(screen.getByText(/not a bill/)).toBeInTheDocument()
    expect(screen.getByText('1 call, not priced')).toBeInTheDocument()
    expect(screen.getByText(/total\s+is a floor/)).toBeInTheDocument()
  })
})
