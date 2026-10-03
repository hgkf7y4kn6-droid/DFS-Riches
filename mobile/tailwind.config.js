/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './components/**/*.{js,jsx,ts,tsx}'],
  presets: [require('nativewind/preset')],
  darkMode: 'media',
  theme: {
    extend: {
      // Values live in global.css as CSS variables (light + dark).
      colors: {
        background: 'rgb(var(--background) / <alpha-value>)',
        foreground: 'rgb(var(--foreground) / <alpha-value>)',
        card: 'rgb(var(--card) / <alpha-value>)',
        primary: 'rgb(var(--primary) / <alpha-value>)',
        'primary-foreground': 'rgb(var(--primary-foreground) / <alpha-value>)',
        accent: 'rgb(var(--accent) / <alpha-value>)',
        'accent-foreground': 'rgb(var(--accent-foreground) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        'muted-foreground': 'rgb(var(--muted-foreground) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        danger: 'rgb(var(--danger) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        info: 'rgb(var(--info) / <alpha-value>)',
        hero: 'rgb(var(--hero) / <alpha-value>)',
        'hero-foreground': 'rgb(var(--hero-foreground) / <alpha-value>)',
        'hero-border': 'rgb(var(--hero-border) / <alpha-value>)',
        'hero-positive': 'rgb(var(--hero-positive) / <alpha-value>)',
        'hero-negative': 'rgb(var(--hero-negative) / <alpha-value>)',
        gold: 'rgb(var(--gold) / <alpha-value>)',
      },
      // Plus Jakarta Sans, loaded in app/_layout.tsx. Each weight is its own
      // family (font-sans-bold etc.) because Android ignores fontWeight on
      // custom fonts.
      fontFamily: {
        sans: ['PlusJakartaSans_400Regular'],
        'sans-regular': ['PlusJakartaSans_400Regular'],
        'sans-medium': ['PlusJakartaSans_500Medium'],
        'sans-semibold': ['PlusJakartaSans_600SemiBold'],
        'sans-bold': ['PlusJakartaSans_700Bold'],
        'sans-extrabold': ['PlusJakartaSans_800ExtraBold'],
      },
    },
  },
  plugins: [],
};
