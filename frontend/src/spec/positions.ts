import type { Position } from '@/api/projects'

export const POSITIONS: { value: Position; label: string }[] = [
  { value: 'top-left', label: 'Top left' },
  { value: 'top-right', label: 'Top right' },
  { value: 'center', label: 'Centre' },
  { value: 'bottom-left', label: 'Bottom left' },
  { value: 'bottom-right', label: 'Bottom right' },
]

export const BANDS: { value: 'top' | 'center' | 'bottom'; label: string }[] = [
  { value: 'top', label: 'Top' },
  { value: 'center', label: 'Centre' },
  { value: 'bottom', label: 'Bottom' },
]
