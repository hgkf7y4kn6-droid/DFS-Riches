// The Tailwind palette (tailwind.config.js) for places that need a JS color
// value rather than a className: tab bar tints, image tintColor, spinners.
export const colors = {
  background: '#FFF9E3',
  foreground: '#081126',
  card: '#FFFFFF',
  primary: '#081126',
  accent: '#EA7A53',
  muted: '#F4ECD6',
  mutedForeground: '#6B7280',
  border: '#E8DFC4',
  success: '#15803D',
  danger: '#B91C1C',
  warning: '#B45309',
  info: '#1D4ED8',
} as const;

/** Font family names, for the few style props that can't take a className. */
export const fonts = {
  regular: 'PlusJakartaSans_400Regular',
  medium: 'PlusJakartaSans_500Medium',
  semibold: 'PlusJakartaSans_600SemiBold',
  bold: 'PlusJakartaSans_700Bold',
  extrabold: 'PlusJakartaSans_800ExtraBold',
} as const;
