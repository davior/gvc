/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    // Notes runs on 5173/8000 and GAM on 5174/8001, and all three run side by side.
    // Pinned, so which app is on which port does not depend on start order.
    port: 5175,
    proxy: {
      // Same-origin in production (nginx proxies both), so the app never needs to
      // know an API host. The dev server mimics that rather than using CORS.
      //
      // This target must track the port the dev backend is started on. Pointing it at
      // a sibling's port does not fail cleanly: that backend shares JWT_SECRET_KEY, so
      // it verifies the token and answers with another app's data.
      '/api': { target: 'http://localhost:8002', changeOrigin: true, ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
  },
})
