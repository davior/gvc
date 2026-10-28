import { Link } from 'react-router-dom'
import type { VideoSpec } from '@/api/projects'
import { Group, Row } from '@/components/SettingsFields'
import { patchSetting } from '@/spec/settings'
import { useThemes } from '@/utils/useThemes'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

/**
 * Which of the user's themes styles what is generated for this video. Part of the
 * spec, so choosing one is an unsaved edit like any other, and a Generate pressed
 * before saving already uses it.
 */
export default function ThemeSettings({ spec, onChange }: Props) {
  const themes = useThemes()
  const current = spec.style?.theme ?? ''
  const theme = themes?.find((t) => t.id === current)
  // An id with no theme behind it: deleted since, or pasted in from someone else.
  // The server ignores it, and so does this, but it says so rather than showing "None".
  const missing = themes !== null && current !== '' && !theme

  const set = (id: string) =>
    onChange(patchSetting(spec, ['style'], { theme: id || undefined }, {}))

  return (
    <Group label="Theme" heading="Theme">
      <Row>
        <label className="flex items-center gap-1">
          Theme
          <select
            className="input w-auto py-0.5"
            aria-label="Theme for this video"
            value={current}
            disabled={themes === null}
            onChange={(e) => set(e.target.value)}
          >
            <option value="">None</option>
            {missing && <option value={current}>A theme that no longer exists</option>}
            {(themes ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.is_default ? ' (default)' : ''}
              </option>
            ))}
          </select>
        </label>
        {themes !== null && themes.length === 0 && (
          <span className="text-gray-500">
            You have no themes yet.{' '}
            <Link to="/settings" className="underline">
              Make one in Settings
            </Link>
            .
          </span>
        )}
      </Row>
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {theme
          ? theme.prompt
            ? `Added to every picture and clip prompt: “${theme.prompt}”`
            : 'This theme adds nothing to prompts yet.'
          : missing
            ? 'Generating ignores it. Choose another, or None.'
            : 'Pictures and clips are generated from their prompts alone.'}
      </p>
    </Group>
  )
}
