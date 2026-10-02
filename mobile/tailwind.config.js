/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './components/**/*.{js,jsx,ts,tsx}'],
  presets: [require('nativewind/preset')],
  theme: {
    extend: {
      colors: {
        background: '#FFF9E3',
        card: '#FFFFFF',
        primary: '#081126',
        accent: '#EA7A53',
        muted: '#6B7280',
        border: '#E8DFC4',
        success: '#15803D',
        danger: '#B91C1C',
        warning: '#B45309',
      },
    },
  },
  plugins: [],
};
