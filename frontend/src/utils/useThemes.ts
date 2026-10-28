import { useEffect, useState } from 'react'
import { themesApi, type Theme } from '@/api/themes'

/**
 * The user's themes, loaded when a component that names one mounts. Not a store: the
 * list is edited on the Settings page, which no editor component outlives, and by the
 * assistant, whose new theme arrives named in a proposal.
 *
 * `wanted` is the theme the project names. When it isn't in the list, the list is read
 * again: an applied proposal can name a theme the assistant made after this mounted.
 * A theme that really is gone costs one extra read per change of `wanted`.
 *
 * null until loaded, and stays null if loading fails: a theme is a nicety on these
 * screens, and its absence must not get in the way of editing or generating.
 */
export function useThemes(wanted?: string): Theme[] | null {
  const [themes, setThemes] = useState<Theme[] | null>(null)
  const missing = !!wanted && themes !== null && !themes.some((t) => t.id === wanted)
  const key = themes === null ? 'first' : missing ? `missing:${wanted}` : 'loaded'
  useEffect(() => {
    if (key === 'loaded') return
    let live = true
    themesApi
      .list()
      .then((rows) => {
        if (live) setThemes(rows)
      })
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [key])
  return themes
}
