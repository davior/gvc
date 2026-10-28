import { useEffect, useState } from 'react'
import { Check, Palette, Pencil, Plus, Trash2 } from 'lucide-react'
import { MAX_THEME_PROMPT, themesApi, type Theme } from '@/api/themes'
import { apiErrorMessage } from '@/api/client'
import { useSavedFlash } from '@/utils/useSavedFlash'

interface Form {
  name: string
  prompt: string
}

const emptyForm = (): Form => ({ name: '', prompt: '' })

/**
 * The theme list: a name and the words added to every generation prompt of a project
 * that uses it. One can be the default, which every new project starts with.
 */
export default function ThemePanel() {
  const [themes, setThemes] = useState<Theme[]>([])
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<Form>(emptyForm())
  const [saving, setSaving] = useState(false)
  const [saved, flashSaved] = useSavedFlash()
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    themesApi
      .list()
      .then(setThemes)
      .catch((err) => setError(apiErrorMessage(err, 'Could not load themes')))

  useEffect(() => {
    void load()
  }, [])

  function startAdd() {
    setEditingId(null)
    setForm(emptyForm())
    setError(null)
    setShowForm(true)
  }

  function startEdit(theme: Theme) {
    setEditingId(theme.id)
    setForm({ name: theme.name, prompt: theme.prompt })
    setError(null)
    setShowForm(true)
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const input = { name: form.name.trim(), prompt: form.prompt.trim() }
      if (editingId) await themesApi.update(editingId, input)
      // The first theme made is the default: with only one there's nothing to choose.
      else await themesApi.create({ ...input, is_default: themes.length === 0 })
      setShowForm(false)
      setEditingId(null)
      flashSaved()
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not save the theme'))
    } finally {
      setSaving(false)
    }
  }

  const setDefault = async (theme: Theme, isDefault: boolean) => {
    setError(null)
    try {
      await themesApi.update(theme.id, { is_default: isDefault })
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not change the default'))
    }
  }

  const remove = async (theme: Theme) => {
    if (
      !confirm(
        `Delete ${theme.name}? Projects using it keep their pictures but generate without a theme.`
      )
    )
      return
    setError(null)
    try {
      await themesApi.remove(theme.id)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not delete the theme'))
    }
  }

  const canSave = form.name.trim() !== '' && !saving

  return (
    <section className="card space-y-4 p-5" aria-label="Themes">
      <header className="flex items-center gap-2">
        <Palette className="h-4 w-4 text-gray-500" />
        <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Themes</h2>
      </header>

      <p className="text-xs text-gray-600 dark:text-gray-400">
        A theme is a look: realistic, 3D, a colour scheme. Its text is added to every
        picture and clip prompt generated for a project that uses it, so a video&apos;s
        generated material matches. Choose a project&apos;s theme in its Settings tab; new
        projects start with the default. The assistant picks one for a video it drafts,
        and makes a new one here when you ask it to or want a look none of these has.
      </p>

      {error && (
        <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </p>
      )}

      {themes.length > 0 && (
        <ul className="space-y-2">
          {themes.map((theme) => (
            <li
              key={theme.id}
              className="flex items-center gap-3 rounded-md border border-gray-200 px-3 py-2 dark:border-gray-800"
            >
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                  <span className="truncate">{theme.name}</span>
                  {theme.is_default && (
                    <span className="shrink-0 rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-green-700 dark:bg-green-900/30 dark:text-green-400">
                      Default
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-gray-500 dark:text-gray-400">
                  {theme.prompt || 'Adds nothing to prompts'}
                </p>
              </div>

              <button
                type="button"
                className="btn btn-ghost text-xs"
                onClick={() => void setDefault(theme, !theme.is_default)}
              >
                {theme.is_default ? 'No default' : 'Make default'}
              </button>
              <button
                type="button"
                className="btn btn-ghost p-1.5"
                aria-label={`Edit ${theme.name}`}
                onClick={() => startEdit(theme)}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="btn btn-ghost p-1.5 text-red-600 dark:text-red-400"
                aria-label={`Delete ${theme.name}`}
                onClick={() => void remove(theme)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {!showForm && (
        <button type="button" className="btn btn-secondary" onClick={startAdd}>
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Add a theme
        </button>
      )}

      {showForm && (
        <div className="space-y-3 border-t border-gray-100 pt-4 dark:border-gray-800">
          <div>
            <label className="label" htmlFor="theme-name">
              Name
            </label>
            <input
              id="theme-name"
              className="input"
              placeholder="Retro 3D"
              maxLength={120}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>

          <div>
            <label className="label" htmlFor="theme-prompt">
              Added to every prompt
            </label>
            <textarea
              id="theme-prompt"
              className="input text-sm"
              rows={4}
              maxLength={MAX_THEME_PROMPT}
              placeholder="Stylised 3D render, soft studio lighting, pastel teal and orange palette"
              value={form.prompt}
              onChange={(e) => setForm({ ...form, prompt: e.target.value })}
            />
            <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              Describe the look, not a subject: the style, the medium, the light, the
              colours. Changing it affects what is generated from now on, in every project
              using this theme.
            </p>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSave}
              onClick={() => void save()}
            >
              {saving ? 'Saving…' : 'Save theme'}
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setShowForm(false)
                setEditingId(null)
                setError(null)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {saved && (
        <p className="flex items-center gap-1.5 text-xs text-green-700 dark:text-green-400">
          <Check className="h-3.5 w-3.5" />
          Saved
        </p>
      )}
    </section>
  )
}
