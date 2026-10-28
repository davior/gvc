import { useEffect, useState } from 'react'
import { themesApi, type Theme } from '@/api/themes'

/**
 * The user's themes, loaded when a component that names one mounts. Not a store: the
 * list is edited only on the Settings page, which no editor component outlives, so a
 * fresh read per mount is never stale.
 *
 * null until loaded, and stays null if loading fails: a theme is a nicety on these
 * screens, and its absence must not get in the way of editing or generating.
 */
export function useThemes(): Theme[] | null {
  const [themes, setThemes] = useState<Theme[] | null>(null)
  useEffect(() => {
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
  }, [])
  return themes
}
