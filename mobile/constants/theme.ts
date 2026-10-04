import { useColorScheme } from 'react-native';

// The color tokens from global.css (CSS variables, light + dark) as JS
// values, for places that can't take a className: tab bar colors, image
// tintColor, spinners, placeholder text. Keep in sync with global.css.
export const lightColors = {
  background: '#FFF9E3',
  foreground: '#081126',
  card: '#FFFFFF',
  primary: '#081126',
  primaryForeground: '#FFF9E3',
  accent: '#EA7A53',
  accentInk: '#BD512E',
  accentForeground: '#FFF9E3',
  gold: '#A67C00',
  muted: '#F4ECD6',
  mutedForeground: '#5D6472',
  border: '#E8DFC4',
  success: '#15803D',
  danger: '#B91C1C',
  warning: '#B45309',
  info: '#1D4ED8',
};

// Rich black matte background, dark slate structure, cool off-white type,
// metallic gold for buttons and active states, emerald and electric red.
export const darkColors: typeof lightColors = {
  background: '#0C0C0D',
  foreground: '#E6EAF0',
  card: '#1C232D',
  primary: '#D4AF37',
  primaryForeground: '#0C0C0D',
  accent: '#D4AF37',
  accentInk: '#D4AF37',
  accentForeground: '#0C0C0D',
  gold: '#D4AF37',
  muted: '#252E3A',
  mutedForeground: '#94A3B8',
  border: '#2E3947',
  success: '#50C878',
  danger: '#E60000',
  warning: '#F0B429',
  info: '#60A5FA',
};

type ThemeColors = typeof lightColors;

/** The palette for the device's current light/dark setting. */
export function useThemeColors(): ThemeColors {
  return useColorScheme() === 'dark' ? darkColors : lightColors;
}

/** Font family names, for the few style props that can't take a className. */
export const fonts = {
  regular: 'PlusJakartaSans_400Regular',
  medium: 'PlusJakartaSans_500Medium',
  semibold: 'PlusJakartaSans_600SemiBold',
  bold: 'PlusJakartaSans_700Bold',
  extrabold: 'PlusJakartaSans_800ExtraBold',
} as const;

/** The floating tab bar's geometry; screens pad their bottom by FLOATING_TAB_BAR.space so content clears it. */
export const FLOATING_TAB_BAR = {
  height: 80,
  margin: 14,
  /** Widest the bar gets (tablets, desktops); it centers beyond that. */
  maxWidth: 560,
  gap: 10,
  /** Height + gap + breathing room, added to the bottom safe-area inset. */
  space: 80 + 10 + 24,
} as const;
