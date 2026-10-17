import { useEffect, useMemo, useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import type { VideoSpec } from '@/api/projects'
import {
  canGenerate,
  dollars,
  estimateCost,
  kindFor,
  type GenerateRef,
} from '@/spec/generation'
import { useGenerationStore } from '@/stores/generations'
import { useProjectStore } from '@/stores/projects'

interface Props {
  assetKey: string
  onClose: () => void
}

/** The project's pictures, as GAM ids: what a clip can be made from. */
function picturesIn(spec: VideoSpec): { id: string; name: string }[] {
  const seen = new Set<string>()
  return Object.entries(spec.assets ?? {}).flatMap(([key, ref]) => {
    const id =
      ref.from === 'gam'
        ? ref.id
        : (ref.from === 'generate' || ref.from === 'search') && ref.result
          ? ref.result.id
          : null
    if (!id || ref.type !== 'image' || seen.has(id)) return []
    seen.add(id)
    return [{ id, name: ref.label ?? (ref.from === 'generate' ? ref.prompt : key) }]
  })
}

/** The GAM id of a registry key, when it is something in the library. */
function gamIdOf(spec: VideoSpec, key: string): string | undefined {
  const ref = spec.assets?.[key]
  if (ref?.from === 'gam') return ref.id
  if ((ref?.from === 'generate' || ref?.from === 'search') && ref.result)
    return ref.result.id
  return undefined
}

/**
 * Generate a placeholder's picture or clip: the prompt, the model and its own options,
 * what it should cost, then Generate. The price is GAM's list price; what fal.ai
 * actually charged is in GAM's usage once it has run.
 */
export default function GenerateDialog({ assetKey, onClose }: Props) {
  const draft = useProjectStore((s) => s.draft)
  const edit = useProjectStore((s) => s.edit)
  const models = useGenerationStore((s) => s.models)
  const loadModels = useGenerationStore((s) => s.loadModels)
  const start = useGenerationStore((s) => s.start)
  const starting = useGenerationStore((s) => s.starting)
  const error = useGenerationStore((s) => s.error)

  const ref = draft?.assets?.[assetKey] as GenerateRef | undefined
  const isVideo = ref?.type === 'video'
  const pictures = useMemo(() => (draft ? picturesIn(draft) : []), [draft])
  const [prompt, setPrompt] = useState(ref?.prompt ?? '')
  const [base, setBase] = useState(
    () =>
      (draft && ref?.base_assets?.map((k) => gamIdOf(draft, k)).find(Boolean)) ??
      pictures[0]?.id ??
      ''
  )
  const imageBases =
    !isVideo && draft
      ? (ref?.base_assets ?? []).flatMap((k) => gamIdOf(draft, k) ?? [])
      : []
  const kind = ref ? kindFor(ref, isVideo ? true : imageBases.length > 0) : ''
  const choices = (models ?? []).filter((m) => m.kind === kind)
  const [modelId, setModelId] = useState('')
  const model = choices.find((m) => m.id === modelId) ?? choices[0]
  const [outputs, setOutputs] = useState(1)
  const [duration, setDuration] = useState('')

  useEffect(() => {
    void loadModels()
  }, [loadModels])

  if (!draft || !ref || ref.from !== 'generate') return null
  const maxOutputs = isVideo ? 1 : Math.min(4, model?.options.max_outputs ?? 4)
  const durations = (model?.options.durations ?? []).map(String)
  const seconds = duration || durations[0]
  const cost = model ? estimateCost(model, Math.min(outputs, maxOutputs), seconds) : null

  async function generate() {
    if (!draft || !ref) return
    // The prompt as sent is the prompt on the placeholder, so "Try again" starts from it.
    const next =
      prompt.trim() === ref.prompt
        ? draft
        : {
            ...draft,
            assets: { ...draft.assets, [assetKey]: { ...ref, prompt: prompt.trim() } },
          }
    if (next !== draft) edit(next)
    const ok = await start({
      asset_key: assetKey,
      prompt: prompt.trim(),
      model_id: model?.id,
      outputs: Math.min(outputs, maxOutputs),
      ...(isVideo && seconds ? { duration: seconds.replace(/s$/, '') } : {}),
      ...(isVideo && base ? { base_gam_ids: [base] } : {}),
      draft_spec: next,
    })
    if (ok) onClose()
  }

  const ready =
    canGenerate(ref) && prompt.trim() !== '' && !!model && (!isVideo || !!base)

  return (
    <div
      className="fixed inset-0 z-40 flex items-start justify-center bg-black/40 p-4 pt-12"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={isVideo ? 'Generate a clip' : 'Generate a picture'}
        className="card flex w-full max-w-lg flex-col gap-3 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <h2 className="flex-1 font-semibold text-gray-900 dark:text-gray-100">
            {isVideo ? 'Generate a clip' : 'Generate a picture'}
          </h2>
          <button
            type="button"
            className="btn btn-ghost p-2"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {!canGenerate(ref) ? (
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Music and sound effects can’t be generated. Find them in your library.
          </p>
        ) : (
          <>
            <label className="space-y-1 text-sm">
              <span className="text-gray-700 dark:text-gray-300">Prompt</span>
              <textarea
                className="input min-h-[6rem] w-full"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </label>

            {models === null ? (
              <p className="text-sm text-gray-500">Loading models…</p>
            ) : choices.length === 0 ? (
              <p className="text-sm text-amber-700 dark:text-amber-300">
                The asset library has no {isVideo ? 'image-to-video' : 'image'} models
                switched on.
              </p>
            ) : (
              <label className="space-y-1 text-sm">
                <span className="text-gray-700 dark:text-gray-300">Model</span>
                <select
                  className="input w-full"
                  value={model?.id}
                  onChange={(e) => setModelId(e.target.value)}
                >
                  {choices.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} ({m.price})
                    </option>
                  ))}
                </select>
              </label>
            )}

            {isVideo && (
              <label className="space-y-1 text-sm">
                <span className="text-gray-700 dark:text-gray-300">Made from</span>
                {pictures.length === 0 ? (
                  <p className="text-amber-700 dark:text-amber-300">
                    A clip is made from a picture. Add one to the video first: find one,
                    or generate one.
                  </p>
                ) : (
                  <select
                    className="input w-full"
                    aria-label="Made from"
                    value={base}
                    onChange={(e) => setBase(e.target.value)}
                  >
                    {pictures.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                )}
              </label>
            )}

            <div className="flex gap-3">
              {maxOutputs > 1 && (
                <label className="space-y-1 text-sm">
                  <span className="text-gray-700 dark:text-gray-300">Pictures</span>
                  <select
                    className="input"
                    aria-label="Pictures"
                    value={Math.min(outputs, maxOutputs)}
                    onChange={(e) => setOutputs(Number(e.target.value))}
                  >
                    {Array.from({ length: maxOutputs }, (_, i) => i + 1).map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {isVideo && durations.length > 0 && (
                <label className="space-y-1 text-sm">
                  <span className="text-gray-700 dark:text-gray-300">Length</span>
                  <select
                    className="input"
                    aria-label="Length"
                    value={seconds}
                    onChange={(e) => setDuration(e.target.value)}
                  >
                    {durations.map((d) => (
                      <option key={d} value={d}>
                        {d.replace(/s$/, '')} seconds
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          </>
        )}

        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3">
          <span className="flex-1 text-xs text-gray-500">
            {model &&
              (cost !== null
                ? `About ${dollars(cost)} on your fal.ai account`
                : `${model.price}, on your fal.ai account`)}
          </span>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!ready || starting}
            onClick={() => void generate()}
          >
            <Sparkles className="mr-1 inline h-4 w-4" />
            {starting ? 'Starting…' : 'Generate'}
          </button>
        </div>
      </div>
    </div>
  )
}
