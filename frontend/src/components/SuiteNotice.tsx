import { ExternalLink } from 'lucide-react'

interface Props {
  suiteUrl: string
}

/**
 * Stands in for the provider form and the usage panel when the assistant runs on Gecko
 * Suite (AI_BACKEND=suite). Both would be wrong there rather than merely redundant: a
 * provider saved here is never called, and spend is recorded in the suite, so this app's
 * own usage table stops growing at the moment of the switch.
 */
export default function SuiteNotice({ suiteUrl }: Props) {
  const base = suiteUrl.replace(/\/$/, '')
  return (
    <section className="card space-y-3 p-4">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        AI is managed in Gecko Suite
      </h3>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        The assistant uses the models chosen in Gecko Suite, one for drafting a new video
        and one for editing an existing one, and what it spends is counted there along
        with Notes and the media library.
      </p>
      <div className="flex flex-wrap gap-2">
        {[
          { path: '/providers', label: 'Providers' },
          { path: '/routing', label: 'Choose models' },
          { path: '/usage', label: 'Usage' },
        ].map(({ path, label }) => (
          <a
            key={path}
            href={`${base}${path}`}
            target="_blank"
            rel="noreferrer noopener"
            className="btn btn-secondary px-3 py-1"
          >
            {label}
            <ExternalLink className="h-3 w-3" />
          </a>
        ))}
      </div>
    </section>
  )
}
