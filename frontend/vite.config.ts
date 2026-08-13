import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // FastAPI backend (server/main.py) runs on 8000; proxying avoids
      // needing CORS for local dev at all, and matches how the built app
      // will be served (behind the same origin) if ever reverse-proxied.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
