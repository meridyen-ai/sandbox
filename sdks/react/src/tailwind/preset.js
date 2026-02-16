/** @type {import('tailwindcss').Config} */
module.exports = {
  theme: {
    extend: {
      colors: {
        'dashboard-bg': '#0d1117',
        'dashboard-surface': '#161b22',
        'dashboard-elevated': '#21262d',
        'dashboard-subtle': '#30363d',
        'dashboard-light': '#f8fafc',
        'dashboard-light-surface': '#ffffff',
        'dashboard-light-elevated': '#f1f5f9',
        'dashboard-light-subtle': '#e2e8f0',
        'dashboard-primary': {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        'dashboard-text': '#f0f6fc',
        'dashboard-text-secondary': '#8b949e',
        'dashboard-text-muted': '#6e7681',
        'dashboard-border': '#30363d',
        'dashboard-border-subtle': '#21262d',
      },
    },
  },
}
