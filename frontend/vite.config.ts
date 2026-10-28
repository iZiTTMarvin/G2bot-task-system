import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发代理：前端 5173 → 本地 FastAPI 8000，保持同源
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
