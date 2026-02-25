import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: parseInt(process.env.VITE_PORT || '5180'),
    allowedHosts: ['sandbox.meridyen.ai'],
    hmr: {
      overlay: false,
    },
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:38082',
        changeOrigin: true,
      },
    },
  },
})
