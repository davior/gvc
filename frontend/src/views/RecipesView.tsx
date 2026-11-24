import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Download, Pencil, Play, Plus, Trash2, Upload } from 'lucide-react'
import {
  MAX_RECIPE_PROMPT,
  type Recipe,
  type RecipeDefaults,
  type RecipeExport,
} from '@/api/recipes'
import type { Aspect } from '@/api/projects'
import { describeDefaults } from '@/recipes/describe'
import { useThemes } from '@/recipes/useThemes'
import { BUILTIN_HELP, inputsOf } from '@/recipes/variables'
import { useAssistantStore } from '@/stores/assistant'
import { useRecipeStore } from '@/stores/recipes'

/**
 * The recipe list: saved requests to run through the assistant, with the settings a
 * video made from one starts with.
 *
 * This page is outside any project, so a recipe run from here makes a new video; run
 * from the assistant on a project, the same recipe changes that video instead.
 */

interface Form {
  name: string
  prompt: string
  tags: string
  themeId: string
  aspect: '' | Aspect
  voice: string
  speed: string
}

const emptyForm = (): Form => ({
  name: '',
  prompt: '',
  tags: '',
  themeId: '',
  aspect: '',
  voice: '',
  speed: '',
})

function formOf(recipe: Recipe): Form {
  const d = recipe.defaults
  return {
    name: recipe.name,
    prompt: recipe.prompt,
    tags: recipe.tags.join(', '),
    themeId: d.theme_id ?? '',
    aspect: d.aspect ?? '',
    voice: d.voice?.voice ?? '',
    speed: d.voice?.speed != null ? String(d.voice.speed) : '',
  }
}

function defaultsOf(form: Form, keep: RecipeDefaults | undefined): RecipeDefaults {
  // What the form doesn't show of a voice (a provider, expressivity: set by the assistant
  // or an import) is kept rather than dropped by an edit that didn't touch it.
  const voice = { ...(keep?.voice ?? {}) }
  voice.voice = form.voice.trim() || null
  const speed = Number(form.speed)
  voice.speed = form.speed.trim() && Number.isFinite(speed) ? speed : null
  const hasVoice = Object.values(voice).some((v) => v != null)
  return {
    theme_id: form.themeId || null,
    aspect: form.aspect || null,
    voice: hasVoice ? voice : null,
  }
}

/** FileReader rather than `file.text()`, which older browsers (and jsdom) lack. */
function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file)
  })
}

const tagsOf = (text: string) =>
  text
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean)

export default function RecipesView() {
  const recipes = useRecipeStore((s) => s.recipes)
  const loaded = useRecipeStore((s) => s.loaded)
  const error = useRecipeStore((s) => s.error)
  const load = useRecipeStore((s) => s.load)
  const createRecipe = useRecipeStore((s) => s.create)
  const updateRecipe = useRecipeStore((s) => s.update)
  const removeRecipe = useRecipeStore((s) => s.remove)
  const importMany = useRecipeStore((s) => s.importMany)
  const runRecipe = useAssistantStore((s) => s.runRecipe)
  const themes = useThemes()

  const [query, setQuery] = useState('')
  const [tag, setTag] = useState<string | null>(null)
  const [editing, setEditing] = useState<Recipe | 'new' | null>(null)
  const [form, setForm] = useState<Form>(emptyForm())
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)

  useEffect(() => {
    void load()
  }, [load])

  const allTags = useMemo(
    () => [...new Set(recipes.flatMap((r) => r.tags))].sort(),
    [recipes]
  )
  const q = query.trim().toLowerCase()
  const shown = recipes.filter(
    (r) =>
      (!tag || r.tags.includes(tag)) &&
      (!q || r.name.toLowerCase().includes(q) || r.prompt.toLowerCase().includes(q))
  )
  const themeName = (id: string) => themes.find((t) => t.id === id)?.name
  const inputs = inputsOf(form.prompt)

  function startAdd() {
    setEditing('new')
    setForm(emptyForm())
    setNotice(null)
  }

  function startEdit(recipe: Recipe) {
    setEditing(recipe)
    setForm(formOf(recipe))
    setNotice(null)
  }

  async function save() {
    if (!editing) return
    setSaving(true)
    const input = {
      name: form.name.trim(),
      prompt: form.prompt.trim(),
      tags: tagsOf(form.tags),
      defaults: defaultsOf(form, editing === 'new' ? undefined : editing.defaults),
    }
    const done =
      editing === 'new'
        ? await createRecipe(input)
        : await updateRecipe(editing.id, input)
    setSaving(false)
    if (done) setEditing(null)
  }

  async function remove(recipe: Recipe) {
    if (!confirm(`Delete the recipe ${recipe.name}? Videos made from it are unaffected.`))
      return
    if (editing !== 'new' && editing?.id === recipe.id) setEditing(null)
    await removeRecipe(recipe.id)
  }

  function exportAll() {
    // The same shape Gecko Notes exports, plus the defaults, so the file goes both ways.
    const data: RecipeExport[] = recipes.map((r) => ({
      name: r.name,
      prompt: r.prompt,
      tags: r.tags,
      defaults: r.defaults,
    }))
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'gvc-recipes.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  async function importFile(chosen: File) {
    setNotice(null)
    let items: RecipeExport[]
    try {
      const parsed: unknown = JSON.parse(await readText(chosen))
      if (!Array.isArray(parsed)) throw new Error('not a list')
      items = parsed.filter(
        (x): x is RecipeExport =>
          !!x &&
          typeof x === 'object' &&
          typeof (x as RecipeExport).name === 'string' &&
          typeof (x as RecipeExport).prompt === 'string' &&
          !!(x as RecipeExport).name.trim() &&
          !!(x as RecipeExport).prompt.trim()
      )
    } catch {
      setNotice('That file is not a list of recipes.')
      return
    }
    const result = await importMany(
      items.map((x) => ({ ...x, tags: Array.isArray(x.tags) ? x.tags : [] }))
    )
    if (result)
      setNotice(
        [
          `Imported ${result.imported} recipe${result.imported === 1 ? '' : 's'}.`,
          ...result.skipped,
        ].join(' ')
      )
  }

  const canSave = !!form.name.trim() && !!form.prompt.trim() && !saving

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <header className="flex flex-wrap items-center gap-2">
        <BookOpen className="h-5 w-5 text-gray-500" />
        <h2 className="flex-1 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Recipes
        </h2>
        <button
          type="button"
          className="btn btn-secondary text-sm"
          onClick={exportAll}
          disabled={recipes.length === 0}
        >
          <Download className="mr-1 inline h-4 w-4" />
          Export
        </button>
        <button
          type="button"
          className="btn btn-secondary text-sm"
          onClick={() => file.current?.click()}
        >
          <Upload className="mr-1 inline h-4 w-4" />
          Import
        </button>
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          className="hidden"
          aria-label="Import recipes"
          onChange={(e) => {
            const chosen = e.target.files?.[0]
            e.target.value = ''
            if (chosen) void importFile(chosen)
          }}
        />
        <button type="button" className="btn btn-primary text-sm" onClick={startAdd}>
          <Plus className="mr-1 inline h-4 w-4" />
          New recipe
        </button>
      </header>

      <p className="text-sm text-gray-600 dark:text-gray-400">
        A recipe is a request you make often, saved to run again: &ldquo;a 60-second
        explainer about {'{{topic}}'} for {'{{audience}}'}&rdquo;. Each {'{{input}}'} is
        asked for when it runs. Run one here to make a new video, or from the assistant on
        a project to change that video. You can also ask the assistant to write a recipe
        or change one; it shows you the change to save. Files exported from Gecko Notes
        import as they are.
      </p>

      {(error || notice) && (
        <p
          role={error ? 'alert' : 'status'}
          className={`rounded-md border px-3 py-2 text-xs ${
            error
              ? 'border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300'
              : 'border-gray-200 bg-white text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300'
          }`}
        >
          {error || notice}
        </p>
      )}

      {editing && (
        <form
          className="card space-y-3 p-4"
          aria-label={editing === 'new' ? 'New recipe' : `Edit ${editing.name}`}
          onSubmit={(e) => {
            e.preventDefault()
            if (canSave) void save()
          }}
        >
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700 dark:text-gray-300">Name</span>
            <input
              className="input w-full"
              aria-label="Name"
              value={form.name}
              maxLength={120}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700 dark:text-gray-300">Prompt</span>
            <textarea
              className="input min-h-[8rem] w-full resize-y"
              aria-label="Prompt"
              value={form.prompt}
              maxLength={MAX_RECIPE_PROMPT}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
            />
            <span className="block text-xs text-gray-500" aria-live="polite">
              {inputs.length
                ? `Asks for: ${inputs.join(', ')}.`
                : 'Asks for nothing. Write {{a name}} for what changes between runs.'}{' '}
              Filled in by themselves: {BUILTIN_HELP}.
            </span>
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700 dark:text-gray-300">Tags</span>
            <input
              className="input w-full"
              aria-label="Tags"
              placeholder="short, explainer"
              value={form.tags}
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
            />
          </label>

          <fieldset className="space-y-2">
            <legend className="text-sm text-gray-700 dark:text-gray-300">
              A new video made from it starts with
            </legend>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <label className="space-y-1">
                <span className="text-xs text-gray-500">Theme</span>
                <select
                  className="input w-full"
                  aria-label="Theme"
                  value={form.themeId}
                  onChange={(e) => setForm({ ...form, themeId: e.target.value })}
                >
                  <option value="">Your default</option>
                  {themes.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                  {form.themeId && !themeName(form.themeId) && (
                    <option value={form.themeId}>A deleted theme</option>
                  )}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs text-gray-500">Aspect</span>
                <select
                  className="input w-full"
                  aria-label="Aspect"
                  value={form.aspect}
                  onChange={(e) =>
                    setForm({ ...form, aspect: e.target.value as Form['aspect'] })
                  }
                >
                  <option value="">Unchanged (16:9)</option>
                  <option value="16:9">16:9 (wide)</option>
                  <option value="9:16">9:16 (vertical)</option>
                  <option value="1:1">1:1 (square)</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs text-gray-500">Voice</span>
                <input
                  className="input w-full"
                  aria-label="Voice"
                  placeholder="Your account's"
                  value={form.voice}
                  onChange={(e) => setForm({ ...form, voice: e.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-gray-500">Voice speed</span>
                <input
                  className="input w-full"
                  aria-label="Voice speed"
                  type="number"
                  min={0.5}
                  max={2}
                  step={0.05}
                  placeholder="1"
                  value={form.speed}
                  onChange={(e) => setForm({ ...form, speed: e.target.value })}
                />
              </label>
            </div>
            <p className="text-xs text-gray-500">
              Only for a new video. Run on a project, a recipe never changes its format.
            </p>
          </fieldset>

          <div className="flex gap-2">
            <button type="submit" className="btn btn-primary text-sm" disabled={!canSave}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              className="btn btn-ghost text-sm"
              onClick={() => setEditing(null)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {recipes.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input min-w-0 flex-1 text-sm"
            aria-label="Search recipes"
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {allTags.map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tag === t}
              className={`rounded-full border px-2 py-0.5 text-xs ${
                tag === t
                  ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300'
                  : 'border-gray-300 text-gray-600 dark:border-gray-600 dark:text-gray-400'
              }`}
              onClick={() => setTag(tag === t ? null : t)}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {loaded && recipes.length === 0 && !editing && (
        <p className="text-sm text-gray-500">
          No recipes yet. Make one, import a file, or ask the assistant: &ldquo;make me a
          recipe for vertical product teasers&rdquo;.
        </p>
      )}

      <ul className="space-y-2" aria-label="Your recipes">
        {shown.map((recipe) => {
          const settings = describeDefaults(recipe.defaults, themeName)
          return (
            <li key={recipe.id} className="card flex items-start gap-3 p-3">
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {recipe.name}
                  {recipe.tags.length > 0 && (
                    <span className="ml-2 text-xs font-normal text-gray-500">
                      {recipe.tags.join(', ')}
                    </span>
                  )}
                </p>
                <p className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                  {recipe.prompt}
                </p>
                <p className="text-xs text-gray-500">
                  {recipe.inputs.length
                    ? `Asks for ${recipe.inputs.join(', ')}`
                    : 'No inputs'}
                  {settings && ` · starts with ${settings}`}
                </p>
              </div>
              <button
                type="button"
                className="btn btn-primary px-2 py-1 text-xs"
                aria-label={`Run ${recipe.name}`}
                title="Run it in the assistant, to make a new video"
                onClick={() => runRecipe(recipe)}
              >
                <Play className="mr-1 inline h-3 w-3" />
                Run
              </button>
              <button
                type="button"
                className="btn btn-ghost p-1.5"
                aria-label={`Edit ${recipe.name}`}
                onClick={() => startEdit(recipe)}
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="btn btn-ghost p-1.5"
                aria-label={`Delete ${recipe.name}`}
                onClick={() => void remove(recipe)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
