import { useEffect, useState } from 'react'
import { themesApi, type Theme } from '@/api/themes'

/** The user's themes, for naming a recipe's default and choosing one. Empty on failure:
 * a theme is then shown as an id-less "a deleted theme", which is the worst case. */
export function useThemes(): Theme[] {
  const [themes, setThemes] = useState<Theme[]>([])
  useEffect(() => {
    let live = true
    themesApi
      .list()
      .then((rows) => live && setThemes(rows))
      .catch(() => undefined)
    return () => {
      live = false
    }
  }, [])
  return themes
}
