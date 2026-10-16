import { useMemo, useState } from 'react'
import { Music, Plus, Trash2 } from 'lucide-react'
import type { GamAsset } from '@/api/gam'
import type { AudioTrack, VideoSpec } from '@/api/projects'
import AnchorSelect from '@/components/AnchorSelect'
import { sceneOptions } from '@/spec/anchors'
import FootageSearch from '@/components/FootageSearch'
import { addTrack, crossfadeInto, removeTrack, updateTrack } from '@/spec/soundtrack'

interface Props {
  spec: VideoSpec
  gamAssets: Record<string, GamAsset | null>
  onChange: (next: VideoSpec) => void
}

/**
 * The video's audio: any number of tracks, each running between two scenes.
 *
 * Changing the soundtrack partway through is a second track starting where the first
 * ends; "crossfade from the track above" overlaps them with matching fades. Tracks
 * are anchored to scenes, so moving or rewriting a scene keeps them where they belong.
 */
export default function SoundtrackPanel({ spec, gamAssets, onChange }: Props) {
  const [adding, setAdding] = useState(false)
  const tracks = spec.audio_tracks ?? []
  const segments = spec.segments
  const nameOf = (track: AudioTrack) => {
    const ref = spec.assets?.[track.asset]
    const id = ref?.from === 'gam' ? ref.id : undefined
    return (id && gamAssets[id]?.name) || ref?.label || track.asset
  }
  const set = (index: number, patch: Partial<AudioTrack>) =>
    onChange(updateTrack(spec, index, patch))

  const options = useMemo(() => sceneOptions(segments), [segments])

  return (
    <div className="space-y-3">
      {tracks.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          No music or sound yet. Add a track from the asset library and choose the scenes
          it plays between.
        </p>
      )}
      {tracks.map((track, index) => {
        const music = (track.kind ?? 'music') === 'music'
        return (
          <section
            key={track.id}
            aria-label={nameOf(track)}
            className="card space-y-2 p-3 text-xs text-gray-700 dark:text-gray-300"
          >
            <div className="flex items-center gap-2">
              <Music className="h-4 w-4 text-gray-400" />
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-900 dark:text-gray-100">
                {nameOf(track)}
              </span>
              <select
                className="input w-auto shrink-0 py-0.5"
                aria-label="Kind of track"
                value={track.kind ?? 'music'}
                onChange={(e) =>
                  set(index, { kind: e.target.value as AudioTrack['kind'] })
                }
              >
                <option value="music">Music</option>
                <option value="sfx">Sound effect</option>
                <option value="voiceover">Voice</option>
              </select>
              <button
                type="button"
                className="btn btn-ghost p-1"
                aria-label="Remove track"
                onClick={() => onChange(removeTrack(spec, index))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <AnchorSelect
                label="From"
                value={track.start}
                options={options}
                onPick={(a) => a && set(index, { start: a })}
              />
              <AnchorSelect
                label="Until"
                value={track.end}
                options={options}
                noneLabel="its own end"
                onPick={(a) => set(index, { end: a })}
              />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1">
                Volume
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  aria-label="Volume"
                  value={track.volume ?? 0.18}
                  onChange={(e) => set(index, { volume: Number(e.target.value) })}
                />
                <span className="w-8">{Math.round((track.volume ?? 0.18) * 100)}%</span>
              </label>
              <label className="flex items-center gap-1">
                Fade in
                <input
                  type="number"
                  min="0"
                  max="15"
                  step="0.5"
                  aria-label="Fade in seconds"
                  className="input w-14 py-0.5"
                  value={track.fade_in ?? 0}
                  onChange={(e) => set(index, { fade_in: Number(e.target.value) })}
                />
              </label>
              <label className="flex items-center gap-1">
                Fade out
                <input
                  type="number"
                  min="0"
                  max="15"
                  step="0.5"
                  aria-label="Fade out seconds"
                  className="input w-14 py-0.5"
                  value={track.fade_out ?? 0}
                  onChange={(e) => set(index, { fade_out: Number(e.target.value) })}
                />
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={track.duck_under_narration ?? music}
                  onChange={(e) => set(index, { duck_under_narration: e.target.checked })}
                />
                Quieter under narration
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={track.loop ?? music}
                  onChange={(e) => set(index, { loop: e.target.checked })}
                />
                Loop to fill
              </label>
            </div>
            {index > 0 && typeof track.start !== 'string' && (
              <button
                type="button"
                className="btn btn-ghost text-xs"
                onClick={() => onChange(crossfadeInto(spec, index, 3))}
              >
                Crossfade from the track above (3 s)
              </button>
            )}
          </section>
        )
      })}
      <button
        type="button"
        className="btn btn-secondary w-full"
        disabled={segments.length === 0}
        onClick={() => setAdding(true)}
      >
        <Plus className="mr-1 inline h-4 w-4" />
        Add music or sound
      </button>
      {adding && (
        <FootageSearch
          title="Music or sound"
          purpose="track"
          initialType="audio"
          onClose={() => setAdding(false)}
          onPick={(hit) => {
            onChange(
              addTrack(
                spec,
                hit.asset,
                'music',
                segments[0].id,
                segments[segments.length - 1].id
              )
            )
            setAdding(false)
          }}
        />
      )}
    </div>
  )
}
