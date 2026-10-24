import type { GamAsset } from '@/api/gam'
import type { Segment, VideoSpec } from '@/api/projects'
import { footageOf } from '@/spec/clip'
import FrameEditor from '@/components/FrameEditor'
import OverlayEditor from '@/components/OverlayEditor'
import {
  DEFAULT_PATH,
  MOTIONS,
  TRANSITIONS,
  motionLabel,
  setMotion,
  setTransition,
} from '@/spec/scene'
import { hasProjectOverlays, setSceneChrome } from '@/spec/settings'

interface Props {
  spec: VideoSpec
  index: number
  segment: Segment
  gamAssets: Record<string, GamAsset | null>
  onChange: (next: VideoSpec) => void
}

const ASPECTS: Record<string, number> = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1 }

/**
 * How a scene comes in and how its picture moves. "Project default" removes the
 * scene's own setting, so changing the project's default later changes this scene too.
 */
export default function SceneSettings({
  spec,
  index,
  segment,
  gamAssets,
  onChange,
}: Props) {
  const transition = segment.transition_in
  // `footageOf`, not a lookup of its own: a generated picture is as much a still as
  // one picked from the library, and a second copy of this resolution once left
  // generated pictures without a Camera control.
  const picture = footageOf(spec, segment, gamAssets)
  const isStill = picture?.asset_type === 'image'
  const motion = segment.visual?.motion
  const outputAspect = ASPECTS[spec.output?.aspect ?? '16:9'] ?? 16 / 9
  const pictureAspect =
    picture?.width && picture?.height ? picture.width / picture.height : outputAspect

  return (
    <div className="space-y-2 text-xs text-gray-600 dark:text-gray-300">
      <div className="flex flex-wrap items-center gap-2">
        {index > 0 && (
          <label className="flex items-center gap-1">
            In with
            <select
              className="input w-auto py-0.5"
              aria-label="Transition into this scene"
              value={transition?.style ?? ''}
              onChange={(e) =>
                onChange(
                  setTransition(
                    spec,
                    index,
                    e.target.value
                      ? {
                          style: e.target.value,
                          ...(transition?.duration !== undefined
                            ? { duration: transition.duration }
                            : {}),
                        }
                      : undefined
                  )
                )
              }
            >
              <option value="">Project default</option>
              {TRANSITIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            {transition?.style && transition.style !== 'none' && (
              <input
                type="number"
                min="0.1"
                max="3"
                step="0.1"
                aria-label="Transition length in seconds"
                className="input w-16 py-0.5"
                placeholder={String(spec.style?.transition?.duration ?? 0.6)}
                value={transition.duration ?? ''}
                onChange={(e) =>
                  onChange(
                    setTransition(spec, index, {
                      style: transition.style,
                      ...(e.target.value ? { duration: Number(e.target.value) } : {}),
                    })
                  )
                }
              />
            )}
          </label>
        )}
        {isStill && (
          <label className="flex items-center gap-1">
            Camera
            <select
              className="input w-auto py-0.5"
              aria-label="Ken Burns move"
              value={motion?.effect ?? ''}
              onChange={(e) => {
                const effect = e.target.value
                onChange(
                  setMotion(
                    spec,
                    index,
                    !effect
                      ? undefined
                      : effect === 'path'
                        ? { effect: 'path', ...DEFAULT_PATH }
                        : { effect }
                  )
                )
              }}
            >
              <option value="">
                Project default ({motionLabel(spec.style?.motion?.effect)})
              </option>
              {MOTIONS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {isStill && motion?.effect === 'path' && motion.from && motion.to && (
        <FrameEditor
          imageUrl={picture?.file_url ?? picture?.thumb_url ?? null}
          pictureAspect={pictureAspect}
          outputAspect={outputAspect}
          from={motion.from}
          to={motion.to}
          onChange={(frames) =>
            onChange(setMotion(spec, index, { ...motion, ...frames }))
          }
        />
      )}
      {hasProjectOverlays(spec) && (
        <label className="flex items-center gap-1">
          Project overlays
          <select
            className="input w-auto py-0.5"
            aria-label="Project overlays on this scene"
            value={segment.chrome === undefined ? '' : String(segment.chrome)}
            onChange={(e) =>
              onChange(
                setSceneChrome(
                  spec,
                  index,
                  e.target.value === '' ? undefined : e.target.value === 'true'
                )
              )
            }
          >
            <option value="">
              Default (
              {segment.role === 'intro' || segment.role === 'outro' ? 'off' : 'on'})
            </option>
            <option value="true">Show watermark, text and wave</option>
            <option value="false">Hide them on this scene</option>
          </select>
        </label>
      )}
      <details
        open={(segment.overlays ?? []).some(
          (o) => o.type !== 'quote' && o.type !== 'code'
        )}
      >
        <summary className="cursor-pointer select-none">On screen</summary>
        <div className="mt-1.5">
          <OverlayEditor
            spec={spec}
            index={index}
            segment={segment}
            gamAssets={gamAssets}
            onChange={onChange}
          />
        </div>
      </details>
    </div>
  )
}
