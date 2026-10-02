/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './components/**/*.{js,jsx,ts,tsx}'],
  presets: [require('nativewind/preset')],
  theme: {
    extend: {
      colors: {
        background: '#FFF9E3',
        foreground: '#081126',
        card: '#FFFFFF',
        primary: '#081126',
        accent: '#EA7A53',
        muted: '#F4ECD6',
        'muted-foreground': '#6B7280',
        border: '#E8DFC4',
        success: '#15803D',
        danger: '#B91C1C',
        warning: '#B45309',
        info: '#1D4ED8',
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
