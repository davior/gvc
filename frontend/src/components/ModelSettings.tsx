import { useEffect } from 'react'
import type { GenerationModel } from '@/api/generations'
import type { ProjectModels, VideoSpec } from '@/api/projects'
import { Group, Row } from '@/components/SettingsFields'
import { patchSetting } from '@/spec/settings'
import { useGenerationStore } from '@/stores/generations'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

const KINDS: { kind: keyof ProjectModels; label: string }[] = [
  { kind: 'text_to_image', label: 'Pictures' },
  { kind: 'image_to_image', label: 'Edited pictures' },
  { kind: 'image_to_video', label: 'Clips' },
]

/**
 * Which of GAM's models generate for this video, per kind. In the spec (S6) like the
 * theme, so a choice is an ordinary edit and reaches the assistant's pictures as well
 * as the Generate dialog. "Library default" leaves the kind to the user's default in
 * GAM's settings, or GAM's own order without one.
 */
export default function ModelSettings({ spec, onChange }: Props) {
  const models = useGenerationStore((s) => s.models)
  const loadModels = useGenerationStore((s) => s.loadModels)
  const chosen: ProjectModels = spec.style?.models ?? {}

  useEffect(() => {
    void loadModels()
  }, [loadModels])

  const set = (kind: keyof ProjectModels, endpoint: string) => {
    const next: ProjectModels = { ...chosen, [kind]: endpoint || undefined }
    if (!endpoint) delete next[kind]
    onChange(
      patchSetting(
        spec,
        ['style'],
        { models: Object.keys(next).length > 0 ? next : undefined },
        {}
      )
    )
  }

  return (
    <Group label="Generation models" heading="Generation models">
      {KINDS.map(({ kind, label }) => {
        const ofKind = (models ?? []).filter((m) => m.kind === kind)
        const current = chosen[kind] ?? ''
        // Named by the spec but not offered by GAM: switched off, removed, or a spec
        // from another library. Generating passes over it, and this says so.
        const missing =
          models !== null &&
          current !== '' &&
          !ofKind.some((m) => m.endpoint_id === current)
        const fallback = ofKind.find((m) => m.is_default) ?? ofKind[0]
        return (
          <Row key={kind}>
            <label className="flex items-center gap-1">
              {label}
              <select
                className="input w-auto py-0.5"
                aria-label={`Model for ${label.toLowerCase()}`}
                value={current}
                disabled={models === null}
                onChange={(e) => set(kind, e.target.value)}
              >
                <option value="">{defaultLabel(fallback)}</option>
                {missing && (
                  <option value={current}>{current} (not in the library)</option>
                )}
                {ofKind.map((m) => (
                  <option key={m.id} value={m.endpoint_id}>
                    {m.label} ({m.price})
                  </option>
                ))}
              </select>
            </label>
          </Row>
        )
      })}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        Used by Generate and by the assistant. Set your default for every video in the
        asset library’s Settings.
      </p>
    </Group>
  )
}

function defaultLabel(model: GenerationModel | undefined): string {
  return model ? `Library default (${model.label})` : 'Library default'
}
