import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // ketcher-react/ketcher-core (built for a webpack/CRA-style bundler that
  // defines process.env.NODE_ENV globally) reference bare `process.env` at
  // module scope -- Vite doesn't polyfill Node globals in the browser, so
  // without this the whole app fails to mount ("process is not defined")
  // the moment ketcher-react's module graph is evaluated, not just when
  // the builder modal opens.
  define: {
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV ?? 'development'),
    // Same story as process.env above -- some of ketcher-core's deps
    // reference the Node global `global` at module scope.
    global: 'globalThis',
  },
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
