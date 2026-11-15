import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Build de production uniquement. Le résultat (dist/) est servi par le backend
// FastAPI sur /app via frontend_dir dans backend/config.yml.
// Base '/app/' pour que les assets et routes SPA fonctionnent sous /app.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  base: '/app/',
})
