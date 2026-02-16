import sandboxUIPreset from '@meridyen/sandbox-ui/tailwind-preset'

/** @type {import('tailwindcss').Config} */
export default {
  presets: [sandboxUIPreset],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "../sdks/react/src/**/*.{ts,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {},
  },
  plugins: [],
}
