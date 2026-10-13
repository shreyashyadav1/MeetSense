/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const LOCAL_BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Lets the app run with VITE_API_URL="" (same-origin URLs) against a local backend.
    proxy: {
      '/api': LOCAL_BACKEND,
      '/health': LOCAL_BACKEND,
      '/ws': { target: LOCAL_BACKEND, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    clearMocks: true,
    restoreMocks: true,
    unstubGlobals: true,
  },
})
