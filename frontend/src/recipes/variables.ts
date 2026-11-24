/**
 * A recipe's placeholders, as the server reads them (`backend/app/services/recipes.py`):
 * `{{ name }}`, matched ignoring case, spaces, `_` and `-`, which is Gecko Notes' rule,
 * so a recipe imported from there reads the same. The server fills them in for a run;
 * this is for the editor's list of inputs, the run form and the live preview.
 */

const PLACEHOLDER = /\{\{\s*([^{}]+?)\s*\}\}/g

/** Filled in by the run itself, never asked for. */
const BUILTINS = new Set([
  'title',
  'videotitle',
  'projecttitle',
  'notetitle',
  'date',
  'time',
])

export const BUILTIN_HELP = '{{title}} (the open video), {{date}}, {{time}}'

export function normalizeKey(key: string): string {
  return key.replace(/[\s_-]+/g, '').toLowerCase()
}

/** Every distinct placeholder, as first written, in order. */
export function placeholders(prompt: string): string[] {
  const seen = new Set<string>()
  const found: string[] = []
  for (const match of prompt.matchAll(PLACEHOLDER)) {
    const key = normalizeKey(match[1])
    if (key && !seen.has(key)) {
      seen.add(key)
      found.push(match[1].trim())
    }
  }
  return found
}

/** The placeholders a run asks for. */
export function inputsOf(prompt: string): string[] {
  return placeholders(prompt).filter((p) => !BUILTINS.has(normalizeKey(p)))
}

/** The prompt with each placeholder that has a value filled in; the rest left as typed. */
export function render(prompt: string, values: Record<string, string>): string {
  const table = new Map<string, string>()
  for (const [key, value] of Object.entries(values)) {
    if (value.trim()) table.set(normalizeKey(key), value.trim())
  }
  return prompt.replace(
    PLACEHOLDER,
    (whole, raw: string) => table.get(normalizeKey(raw)) ?? whole
  )
}

/** The asker's own date and time, sent with a run so they are local, not the server's. */
export function clockValues(now = new Date()): Record<string, string> {
  return {
    date: now.toLocaleDateString(undefined, { dateStyle: 'long' }),
    time: now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
  }
}
