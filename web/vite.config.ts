import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built app ships inside the Python package (static/app) so `pip install` alone serves it.
// In development, `vite` proxies /api to the FastAPI server on 8765.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../src/anaplan_architect/static/app',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5180,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
