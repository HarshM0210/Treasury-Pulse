import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Django API runs on :8000. Proxying /api through Vite keeps the browser
// on one origin, so the session cookie and CSRF token just work.
const API = process.env.VITE_API_PROXY || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: API, changeOrigin: true },
      '/health': { target: API, changeOrigin: true },
    },
  },
})
