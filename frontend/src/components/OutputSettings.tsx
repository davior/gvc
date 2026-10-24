import type { Aspect, Quality, Resolution, SubtitleMode, VideoSpec } from '@/api/projects'
import { OUTPUT_DEFAULTS, setOutput } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  onChange: (next: VideoSpec) => void
}

const ASPECTS: { value: Aspect; label: string }[] = [
  { value: '16:9', label: 'Widescreen 16:9' },
  { value: '9:16', label: 'Vertical 9:16' },
  { value: '1:1', label: 'Square 1:1' },
]

const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: '720p', label: '720p' },
  { value: '1080p', label: '1080p' },
  { value: '4k', label: '4K' },
]

const QUALITIES: { value: Quality; label: string }[] = [
  { value: 'preview', label: 'Fast, larger file' },
  { value: 'standard', label: 'Standard' },
  { value: 'high', label: 'High, slower' },
]

const SUBTITLES: { value: SubtitleMode; label: string }[] = [
  { value: 'off', label: 'None' },
  { value: 'sidecar', label: 'A separate .srt file' },
  { value: 'soft', label: 'Inside the video, can be switched off' },
  { value: 'burn', label: 'Drawn onto the picture' },
]

/**
 * The finished file: its shape, size, frame rate and extras. Aspect is also what the
 * scene editor frames a camera move against, so changing it changes those previews.
 */
export default function OutputSettings({ spec, onChange }: Props) {
  const o = { ...OUTPUT_DEFAULTS, ...(spec.output ?? {}) }
  const select = <T extends string>(
    label: string,
    value: T,
    options: { value: T; label: string }[],
    set: (v: T) => void
  ) => (
    <label className="flex items-center gap-1">
      {label}
      <select
        className="input w-auto py-0.5"
        aria-label={label}
        value={value}
        onChange={(e) => set(e.target.value as T)}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <section aria-label="Output" className="card space-y-2 p-3 text-sm">
      <h2 className="font-medium text-gray-900 dark:text-gray-100">The video file</h2>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark:text-gray-300">
        {select('Shape', o.aspect, ASPECTS, (aspect) =>
          onChange(setOutput(spec, { aspect }))
        )}
        {select('Size', o.resolution, RESOLUTIONS, (resolution) =>
          onChange(setOutput(spec, { resolution }))
        )}
        {select('Quality', o.quality, QUALITIES, (quality) =>
          onChange(setOutput(spec, { quality }))
        )}
        <label className="flex items-center gap-1">
          Frames per second
          <input
            type="number"
            min="12"
            max="60"
            step="1"
            aria-label="Frames per second"
            className="input w-16 py-0.5"
            value={o.fps}
            onChange={(e) => {
              // Out of range is refused by the spec on save; hold the box to it here.
              const fps = Math.round(Number(e.target.value))
              if (fps >= 12 && fps <= 60) onChange(setOutput(spec, { fps }))
            }}
          />
        </label>
        {select('Subtitles', o.subtitles, SUBTITLES, (subtitles) =>
          onChange(setOutput(spec, { subtitles }))
        )}
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs text-gray-600 dark:text-gray-300">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={o.chapters}
            onChange={(e) => onChange(setOutput(spec, { chapters: e.target.checked }))}
          />
          Chapter marks in the file
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={o.thumbnail}
            onChange={(e) => onChange(setOutput(spec, { thumbnail: e.target.checked }))}
          />
          Cover picture
        </label>
      </div>
    </section>
  )
}
