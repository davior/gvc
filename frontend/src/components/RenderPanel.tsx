import { useEffect, useState } from 'react'
import {
  Check,
  Clapperboard,
  Copy,
  Download,
  ExternalLink,
  Eye,
  Library,
  Square,
  Trash2,
} from 'lucide-react'
import { ACTIVE, type Render } from '@/api/renders'
import { useRenderStore } from '@/stores/renders'
import { clock } from '@/spec/footage'

interface Props {
  projectId: string
  /** Unsaved edits: a render is of the saved version, so they would be left out. */
  dirty: boolean
  /** The saved version, so the estimate follows saves. */
  version: number
}

function size(bytes: number | null): string {
  if (!bytes) return ''
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.round(bytes / 1024)} KB`
}

function Status({ render }: { render: Render }) {
  if (render.status === 'done')
    return <span className="text-green-700 dark:text-green-400">Done</span>
  if (render.status === 'error')
    return <span className="text-red-700 dark:text-red-400">Failed</span>
  if (render.status === 'cancelled')
    return <span className="text-gray-500">Cancelled</span>
  return (
    <span className="text-blue-700 dark:text-blue-400">{render.stage || 'Waiting'}</span>
  )
}

/**
 * Previewing and rendering the saved project, and the renders made so far.
 *
 * A preview is small and fast, and shows placeholders as slates; a full render needs
 * every placeholder found. Both render the *saved* version, so unsaved edits block
 * them rather than being silently left out.
 */
export default function RenderPanel({ projectId, dirty, version }: Props) {
  const renders = useRenderStore((s) => s.renders)
  const estimate = useRenderStore((s) => s.estimate)
  const starting = useRenderStore((s) => s.starting)
  const error = useRenderStore((s) => s.error)
  const load = useRenderStore((s) => s.load)
  const refreshEstimate = useRenderStore((s) => s.refreshEstimate)
  const start = useRenderStore((s) => s.start)
  const cancel = useRenderStore((s) => s.cancel)
  const remove = useRenderStore((s) => s.remove)
  const saving = useRenderStore((s) => s.saving)
  const saveToGam = useRenderStore((s) => s.saveToGam)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    void load(projectId)
  }, [projectId, load])

  useEffect(() => {
    void refreshEstimate()
  }, [version, refreshEstimate])

  const running = renders.find((r) => ACTIVE.includes(r.status))
  const latest = renders.find((r) => r.status === 'done')
  const previewBlocks = estimate?.blocks_preview ?? []
  const renderBlocks = estimate?.blocks_render ?? []
  const busy = starting || !!running

  return (
    <div className="space-y-4">
      {estimate && (
        <p className="text-sm text-gray-700 dark:text-gray-300">
          About {estimate.seconds_is_floor ? 'at least ' : ''}
          {clock(estimate.seconds)} long, with {estimate.narration_chars.toLocaleString()}{' '}
          characters of narration.
        </p>
      )}
      {dirty && (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          Save first: a render is made from the saved version.
        </p>
      )}
      {renderBlocks.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-amber-800 dark:text-amber-200">
          {renderBlocks.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={dirty || busy || previewBlocks.length > 0}
          onClick={() => void start(true)}
          title="Small and quick; placeholders show as slates"
        >
          <Eye className="mr-1 inline h-4 w-4" />
          Preview
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={dirty || busy || renderBlocks.length > 0}
          onClick={() => void start(false)}
        >
          <Clapperboard className="mr-1 inline h-4 w-4" />
          Render
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {running && (
        <div className="card space-y-2 p-3" aria-label="Rendering">
          <div className="flex items-center gap-2 text-sm">
            <span className="flex-1 text-gray-700 dark:text-gray-300">
              {running.preview ? 'Preview' : 'Render'} of version {running.version}:{' '}
              {running.stage || 'waiting to start'}
              {running.detail && ` (${running.detail})`}
            </span>
            <button
              type="button"
              className="btn btn-ghost text-xs"
              onClick={() => void cancel(running.id)}
            >
              <Square className="mr-1 inline h-3 w-3" />
              Stop
            </button>
          </div>
          <div className="h-2 overflow-hidden rounded bg-gray-200 dark:bg-gray-700">
            <div
              role="progressbar"
              aria-valuenow={running.progress}
              aria-valuemin={0}
              aria-valuemax={100}
              className="h-full bg-primary-600 transition-all"
              style={{ width: `${running.progress}%` }}
            />
          </div>
        </div>
      )}

      {latest?.video_url && (
        <div className="space-y-2" aria-label="Latest render">
          <video
            key={latest.id}
            controls
            preload="metadata"
            poster={latest.poster_url ?? undefined}
            className="w-full rounded bg-black"
            src={latest.video_url}
          />
          {latest.description && (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className="flex-1">Description: chapters and credits</span>
                <button
                  type="button"
                  className="btn btn-ghost px-1 py-0.5 text-xs"
                  onClick={() => {
                    void navigator.clipboard?.writeText(latest.description ?? '')
                    setCopied(true)
                    setTimeout(() => setCopied(false), 1500)
                  }}
                >
                  {copied ? (
                    <Check className="mr-1 inline h-3 w-3" />
                  ) : (
                    <Copy className="mr-1 inline h-3 w-3" />
                  )}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                {latest.description}
              </pre>
            </div>
          )}
          {latest.warnings.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-amber-700 dark:text-amber-300">
              {latest.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {renders.length > 0 && (
        <ul className="space-y-1" aria-label="Renders">
          {renders.map((render) => (
            <li key={render.id} className="card flex items-center gap-3 p-2 text-xs">
              <span className="w-24 font-medium text-gray-900 dark:text-gray-100">
                {render.preview ? 'Preview' : 'Render'} v{render.version}
              </span>
              <span className="flex-1">
                <Status render={render} />
                {render.error && (
                  <span className="text-red-700 dark:text-red-400">: {render.error}</span>
                )}
              </span>
              {render.duration !== null && <span>{clock(render.duration)}</span>}
              <span>{size(render.size_bytes)}</span>
              {render.video_url && (
                <a
                  className="btn btn-ghost p-1"
                  href={render.video_url}
                  download
                  aria-label="Download video"
                >
                  <Download className="h-4 w-4" />
                </a>
              )}
              {render.status === 'done' &&
                !render.preview &&
                (render.gam_asset_url ? (
                  <a
                    className="btn btn-ghost px-1 py-0.5"
                    href={render.gam_asset_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    In GAM
                    <ExternalLink className="ml-1 inline h-3 w-3" />
                  </a>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost px-1 py-0.5"
                    disabled={saving !== null}
                    onClick={() => void saveToGam(render.id)}
                    title="File this video in your asset library"
                  >
                    <Library className="mr-1 inline h-3 w-3" />
                    {saving === render.id ? 'Saving…' : 'Save to GAM'}
                  </button>
                ))}
              {render.subtitles_url && (
                <a
                  className="btn btn-ghost px-1 py-0.5"
                  href={render.subtitles_url}
                  download
                >
                  .srt
                </a>
              )}
              {!ACTIVE.includes(render.status) && (
                <button
                  type="button"
                  className="btn btn-ghost p-1"
                  aria-label="Delete render"
                  onClick={() => void remove(render.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
