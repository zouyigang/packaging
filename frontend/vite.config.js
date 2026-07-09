import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 代理到后端 FastAPI（默认 8000），避免 CORS 烦恼。
export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          const normalized = id.replaceAll('\\', '/')
          if (
            normalized.includes('/node_modules/react/') ||
            normalized.includes('/node_modules/react-dom/') ||
            normalized.includes('/node_modules/scheduler/')
          ) {
            return 'react-vendor'
          }
          if (
            normalized.includes('/node_modules/antd/') ||
            normalized.includes('/node_modules/@ant-design/icons/')
          ) {
            return 'antd-vendor'
          }
          if (
            normalized.includes('/node_modules/three/')
          ) {
            return 'three-core'
          }
          if (
            normalized.includes('/node_modules/@react-three/fiber/') ||
            normalized.includes('/node_modules/@react-three/drei/')
          ) {
            return 'three-react'
          }
          if (normalized.includes('/node_modules/zustand/')) {
            return 'state-vendor'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
