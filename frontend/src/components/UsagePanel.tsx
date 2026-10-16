import { useEffect, useState } from 'react'
import { Receipt } from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import { formatCost, usageApi, type UsageSummary } from '@/api/usage'

/** What the assistant has cost so far, always said to be an estimate. */
export default function UsagePanel() {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    usageApi
      .summary()
      .then((s) => live && setSummary(s))
      .catch((err) => live && setError(apiErrorMessage(err)))
    return () => {
      live = false
    }
  }, [])

  const totals = summary?.totals
  const unpriced = totals ? totals.total_events - totals.priced_events : 0

  return (
    <section className="card space-y-3 p-5" aria-label="Spend">
      <header className="flex items-center gap-2">
        <Receipt className="h-4 w-4 text-gray-500" />
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          What the assistant has cost
        </h2>
      </header>
      {error && <p className="text-xs text-red-700 dark:text-red-400">{error}</p>}
      {totals && totals.total_events === 0 && (
        <p className="text-xs text-gray-600 dark:text-gray-400">Nothing yet.</p>
      )}
      {totals && totals.total_events > 0 && (
        <>
          <div>
            <p className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
              {formatCost(totals.cost, totals.currency)}
            </p>
            <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
              An estimate from published list prices, not a bill. Check your
              provider&apos;s dashboard for what you were charged.
            </p>
          </div>
          <dl className="space-y-1 border-t border-gray-100 pt-3 text-xs dark:border-gray-800">
            <div className="flex justify-between">
              <dt className="text-gray-500 dark:text-gray-400">Tokens</dt>
              <dd className="text-gray-900 dark:text-gray-100">
                {totals.tokens.toLocaleString()}
              </dd>
            </div>
            {summary.by_provider.map((row) => (
              <div key={`${row.provider}/${row.model}`} className="flex justify-between">
                <dt className="text-gray-500 dark:text-gray-400">
                  {row.model || row.provider}
                </dt>
                <dd className="text-gray-900 dark:text-gray-100">
                  {row.cost === null
                    ? `${row.events} call${row.events === 1 ? '' : 's'}, not priced`
                    : formatCost(row.cost, totals.currency)}
                </dd>
              </div>
            ))}
          </dl>
          {unpriced > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {unpriced} call{unpriced === 1 ? '' : 's'} could not be priced, so the total
              is a floor.
            </p>
          )}
        </>
      )}
    </section>
  )
}
