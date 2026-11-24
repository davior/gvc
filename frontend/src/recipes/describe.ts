import type { RecipeDefaults } from '@/api/recipes'

/** A recipe's defaults in a few words: "Noir · 9:16 · voice aura, ×1.2". */
export function describeDefaults(
  defaults: RecipeDefaults,
  themeName: (id: string) => string | undefined
): string {
  const parts: string[] = []
  if (defaults.theme_id) parts.push(themeName(defaults.theme_id) ?? 'a deleted theme')
  if (defaults.aspect) parts.push(defaults.aspect)
  const voice = defaults.voice
  if (voice) {
    const bits = [
      voice.voice,
      voice.provider && voice.provider !== 'auto' ? voice.provider : null,
      voice.speed != null && voice.speed !== 1 ? `×${voice.speed}` : null,
    ].filter(Boolean)
    if (bits.length) parts.push(`voice ${bits.join(', ')}`)
  }
  return parts.join(' · ')
}
