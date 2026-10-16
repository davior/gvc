import client from '@/api/client'

/**
 * What the assistant has spent. Every figure is a list-price estimate, and the UI says
 * so: a cost from the pricing table is a published rate, not a bill.
 */

interface DataResponse<T> {
  data: T
}

export interface UsageTotals {
  total_events: number
  /** Fewer than `total_events` means some calls could not be priced, so `cost` is a
   *  floor rather than the whole story. */
  priced_events: number
  cost: number
  currency: string
  estimated: boolean
  tokens: number
}

export interface ProviderTotal {
  provider: string
  model: string
  events: number
  units: number
  /** null when nothing in this group could be priced. */
  cost: number | null
}

export interface UsageSummary {
  totals: UsageTotals
  by_provider: ProviderTotal[]
}

export const usageApi = {
  summary(): Promise<UsageSummary> {
    return client.get<DataResponse<UsageSummary>>('/usage').then((r) => r.data.data)
  },

  forProject(projectId: string): Promise<UsageTotals> {
    return client
      .get<DataResponse<UsageTotals>>(`/usage/projects/${projectId}`)
      .then((r) => r.data.data)
  },
}

/**
 * A cost at a precision that does not pretend. A turn costs fractions of a cent to a
 * few cents, and rounding to two decimals would show "$0.00" for work that was not free.
 */
export function formatCost(cost: number, currency = 'USD'): string {
  const symbol = currency === 'USD' ? '$' : `${currency} `
  if (cost === 0) return `${symbol}0.00`
  if (cost < 0.01) return `${symbol}${cost.toFixed(4)}`
  return `${symbol}${cost.toFixed(2)}`
}
