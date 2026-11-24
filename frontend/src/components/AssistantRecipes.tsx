import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Check, Play, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { RecipeDraft, RecipeProposal } from '@/api/assistant'
import type { Recipe } from '@/api/recipes'
import { describeDefaults } from '@/recipes/describe'
import { diffLines } from '@/recipes/diff'
import { useThemes } from '@/recipes/useThemes'
import { useAssistantStore } from '@/stores/assistant'
import { useRecipeStore } from '@/stores/recipes'

/**
 * Recipes in the assistant panel: the picker in the composer, the form a run asks its
 * inputs in, and the card for a change to the list the assistant proposed.
 */

/** The composer's recipe button: pick one to run. */
export function RecipePicker({ disabled }: { disabled: boolean }) {
  const recipes = useRecipeStore((s) => s.recipes)
  const loaded = useRecipeStore((s) => s.loaded)
  const load = useRecipeStore((s) => s.load)
  const runRecipe = useAssistantStore((s) => s.runRecipe)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!loaded) void load()
  }, [loaded, load])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', away)
    return () => window.removeEventListener('mousedown', away)
  }, [open])

  const q = query.trim().toLowerCase()
  const shown = recipes.filter(
    (r) => !q || r.name.toLowerCase().includes(q) || r.tags.some((t) => t.includes(q))
  )

  function pick(recipe: Recipe) {
    runRecipe(recipe)
    setOpen(false)
    setQuery('')
  }

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        className="btn btn-secondary p-2"
        aria-label="Run a recipe"
        title="Run a recipe"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <BookOpen className="h-4 w-4" />
      </button>
      {open && (
        <div
          className="absolute bottom-full left-0 z-40 mb-1 w-64 rounded border border-gray-200 bg-white p-2 shadow-lg dark:border-gray-700 dark:bg-gray-800"
          role="dialog"
          aria-label="Recipes"
        >
          {recipes.length === 0 ? (
            <p className="text-xs text-gray-600 dark:text-gray-400">
              No recipes yet. Make one on the{' '}
              <Link to="/recipes" className="underline" onClick={() => setOpen(false)}>
                Recipes
              </Link>{' '}
              page, or ask the assistant to write one.
            </p>
          ) : (
            <>
              <input
                className="input mb-1 w-full text-xs"
                aria-label="Find a recipe"
                placeholder="Name or tag…"
                value={query}
                autoFocus
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && shown[0]) {
                    e.preventDefault()
                    pick(shown[0])
                  }
                  if (e.key === 'Escape') setOpen(false)
                }}
              />
              <ul className="max-h-60 overflow-auto">
                {shown.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      className="w-full rounded px-2 py-1 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700"
                      onClick={() => pick(r)}
                    >
                      <span className="font-medium">{r.name}</span>
                      {r.tags.length > 0 && (
                        <span className="ml-1 text-gray-500">{r.tags.join(', ')}</span>
                      )}
                    </button>
                  </li>
                ))}
                {shown.length === 0 && (
                  <li className="px-2 py-1 text-xs text-gray-500">No match.</li>
                )}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

interface RunFormProps {
  recipe: Recipe
  /** On a project: the run changes it, and the defaults are not applied. */
  inProject: boolean
  busy: boolean
  onRun: (values: Record<string, string>) => void
  onCancel: () => void
}

/** The inputs of the recipe about to run, one field each. */
export function RecipeRunForm({
  recipe,
  inProject,
  busy,
  onRun,
  onCancel,
}: RunFormProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const themes = useThemes()
  const defaults = describeDefaults(
    recipe.defaults,
    (id) => themes.find((t) => t.id === id)?.name
  )
  const missing = recipe.inputs.filter((i) => !values[i]?.trim())

  return (
    <form
      aria-label={`Run ${recipe.name}`}
      className="space-y-2 rounded border border-primary-200 bg-primary-50/50 p-2 text-xs dark:border-primary-800 dark:bg-primary-900/20"
      onSubmit={(e) => {
        e.preventDefault()
        if (!busy) onRun(values)
      }}
    >
      <div className="flex items-center gap-1">
        <BookOpen className="h-3 w-3 text-primary-600" />
        <p className="flex-1 font-medium text-gray-900 dark:text-gray-100">
          {recipe.name}
        </p>
        <button
          type="button"
          className="btn btn-ghost p-0.5"
          aria-label="Cancel the recipe"
          onClick={onCancel}
        >
          <X className="h-3 w-3" />
        </button>
      </div>
      {recipe.inputs.map((input, i) => (
        <label key={input} className="block space-y-0.5">
          <span className="text-gray-600 dark:text-gray-400">{input}</span>
          <textarea
            className="input min-h-[2rem] w-full resize-y text-xs"
            aria-label={input}
            rows={1}
            autoFocus={i === 0}
            value={values[input] ?? ''}
            onChange={(e) => setValues({ ...values, [input]: e.target.value })}
          />
        </label>
      ))}
      {defaults && (
        <p className="text-gray-500">
          {inProject
            ? `Its settings (${defaults}) are for new videos and won't change this one.`
            : `A new video starts with ${defaults}.`}
        </p>
      )}
      {missing.length > 0 && recipe.inputs.length > 0 && (
        <p className="text-gray-500">
          Left empty, an input stays as written in the recipe.
        </p>
      )}
      <button type="submit" className="btn btn-primary px-2 py-1 text-xs" disabled={busy}>
        <Play className="mr-1 inline h-3 w-3" />
        {inProject ? 'Run on this video' : 'Run'}
      </button>
    </form>
  )
}

function Highlighted({ text }: { text: string }) {
  // The placeholders, picked out, so the inputs a run will ask for are visible.
  const parts = text.split(/(\{\{[^{}]+?\}\})/g)
  return (
    <>
      {parts.map((part, i) =>
        /^\{\{[^{}]+\}\}$/.test(part) ? (
          <mark
            key={i}
            className="rounded bg-amber-100 px-0.5 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  )
}

function PromptDiff({ before, after }: { before: string; after: string }) {
  const lines = useMemo(() => diffLines(before, after), [before, after])
  return (
    <pre
      aria-label="Prompt changes"
      className="max-h-60 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 font-sans dark:bg-gray-900"
    >
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.kind === 'added'
              ? 'bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-200'
              : line.kind === 'removed'
                ? 'bg-red-100 text-red-900 line-through dark:bg-red-900/30 dark:text-red-200'
                : 'text-gray-600 dark:text-gray-400'
          }
        >
          {line.kind === 'added' ? '+ ' : line.kind === 'removed' ? '− ' : '  '}
          <Highlighted text={line.text} />
        </div>
      ))}
    </pre>
  )
}

function Change({
  label,
  before,
  after,
}: {
  label: string
  before: string
  after: string
}) {
  return (
    <p>
      <span className="text-gray-500">{label}: </span>
      <span className="line-through opacity-70">{before || 'none'}</span>
      {' → '}
      <span className="font-medium">{after || 'none'}</span>
    </p>
  )
}

/**
 * A change to the recipe list the assistant proposed. Apart from the video's proposal:
 * nothing reaches the list until Save, which is checked again on the server, so an edit
 * made by hand in the meantime is never overwritten.
 */
export function RecipeCard({
  turnId,
  proposal,
}: {
  turnId: string
  proposal: RecipeProposal
}) {
  const decideRecipe = useAssistantStore((s) => s.decideRecipe)
  const themes = useThemes()
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(proposal.op !== 'create')
  const themeName = (id: string) => themes.find((t) => t.id === id)?.name
  const describe = (d: RecipeDraft | null) =>
    d ? describeDefaults(d.defaults, themeName) : ''
  const { op, before, after, fields, state } = proposal
  const name = (after ?? before)?.name ?? ''

  async function decide(save: boolean) {
    setBusy(true)
    await decideRecipe(turnId, proposal.recipe_ref, save)
    setBusy(false)
  }

  const title =
    op === 'create'
      ? `New recipe: ${name}`
      : op === 'delete'
        ? `Delete recipe: ${name}`
        : `Change recipe: ${before?.name ?? name}`

  return (
    <div
      aria-label={title}
      className="space-y-2 rounded border border-gray-200 p-2 text-xs dark:border-gray-700"
    >
      <p className="flex items-center gap-1 font-medium text-gray-900 dark:text-gray-100">
        <BookOpen className="h-3 w-3" />
        {title}
      </p>

      {op === 'create' && after && (
        <>
          <p className="text-gray-600 dark:text-gray-400">
            {after.inputs.length
              ? `Asks for ${after.inputs.join(', ')}.`
              : 'Asks for nothing.'}
            {after.tags.length > 0 && ` Tagged ${after.tags.join(', ')}.`}
            {describe(after) && ` New videos start with ${describe(after)}.`}{' '}
            <button
              type="button"
              className="text-blue-700 hover:underline dark:text-blue-300"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              {open ? 'Hide the prompt' : 'Read the prompt'}
            </button>
          </p>
          {open && (
            <p className="max-h-60 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 dark:bg-gray-900">
              <Highlighted text={after.prompt} />
            </p>
          )}
        </>
      )}

      {op === 'update' && before && after && (
        <div className="space-y-1 text-gray-700 dark:text-gray-300">
          {fields.includes('name') && (
            <Change label="Name" before={before.name} after={after.name} />
          )}
          {fields.includes('tags') && (
            <Change
              label="Tags"
              before={before.tags.join(', ')}
              after={after.tags.join(', ')}
            />
          )}
          {fields.includes('defaults') && (
            <Change
              label="New videos start with"
              before={describe(before)}
              after={describe(after)}
            />
          )}
          {fields.includes('prompt') && (
            <PromptDiff before={before.prompt} after={after.prompt} />
          )}
        </div>
      )}

      {op === 'delete' && before && (
        <p className="text-gray-600 dark:text-gray-400">
          Videos already made from it are unaffected.
        </p>
      )}

      {state === 'pending' && (
        <div className="flex gap-2">
          <button
            type="button"
            className={`btn px-2 py-1 text-xs ${op === 'delete' ? 'btn-danger' : 'btn-primary'}`}
            disabled={busy}
            onClick={() => void decide(true)}
          >
            {op === 'create'
              ? 'Save recipe'
              : op === 'update'
                ? 'Save changes'
                : 'Delete recipe'}
          </button>
          <button
            type="button"
            className="btn btn-secondary px-2 py-1 text-xs"
            disabled={busy}
            onClick={() => void decide(false)}
          >
            Discard
          </button>
        </div>
      )}
      {state === 'saved' && (
        <p className="flex items-center gap-1 text-green-700 dark:text-green-400">
          <Check className="h-3 w-3" />
          {op === 'delete' ? 'Deleted.' : 'Saved.'}{' '}
          {op !== 'delete' && (
            <Link
              to="/recipes"
              className="text-blue-700 hover:underline dark:text-blue-300"
            >
              See your recipes
            </Link>
          )}
        </p>
      )}
      {state === 'discarded' && <p className="text-gray-500">Discarded.</p>}
    </div>
  )
}
