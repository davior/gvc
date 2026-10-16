import ProviderPanel from '@/components/ProviderPanel'
import UsagePanel from '@/components/UsagePanel'

/** GVC's own settings: the assistant's AI provider, and what it has spent. */
export default function SettingsView() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Settings</h2>
      <ProviderPanel />
      <UsagePanel />
    </div>
  )
}
