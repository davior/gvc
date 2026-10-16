import { formatPath, type SpecIssue } from '@/api/projects'

/** Problems with a spec, each at the path it concerns. */
export default function IssueList({ issues }: { issues: SpecIssue[] }) {
  if (issues.length === 0) return null
  return (
    <ul
      role="alert"
      className="space-y-1 rounded border border-red-200 bg-red-50 p-3 text-sm dark:border-red-800 dark:bg-red-950"
    >
      {issues.map((issue, i) => (
        <li key={i} className="text-red-700 dark:text-red-300">
          <code className="font-mono text-xs">{formatPath(issue.path)}</code>
          {' — '}
          {issue.message}
        </li>
      ))}
    </ul>
  )
}
