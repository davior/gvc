import { useEffect, useState } from 'react'
import { loadConfig, type ClientConfig } from '@/api/config'
import ProviderPanel from '@/components/ProviderPanel'
import SuiteNotice from '@/components/SuiteNotice'
import ThemePanel from '@/components/ThemePanel'
import UsagePanel from '@/components/UsagePanel'

/** GVC's own settings: where the assistant's AI comes from, the themes generation is
 *  styled with, and what the assistant has spent. With Gecko Suite behind the assistant
 *  the first and last are the suite's to manage, so this links there instead. */
export default function SettingsView() {
  const [config, setConfig] = useState<ClientConfig | null>(null)

  useEffect(() => {
    let stale = false
    loadConfig()
      .then((c) => !stale && setConfig(c))
      .catch(() => {
        // Not fatal: without it this shows the app's own panels, which is the old behaviour.
      })
    return () => {
      stale = true
    }
  }, [])

  const onSuite = config?.ai_backend === 'suite'

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Settings</h2>
      {onSuite ? <SuiteNotice suiteUrl={config.suite_base_url} /> : <ProviderPanel />}
      <ThemePanel />
      {!onSuite && <UsagePanel />}
    </div>
  )
}
