import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// ------------------------------------------------------------
// 双页面构建：
//   index.html -> 客户端聊天页
//   admin.html -> 管理端（登录 + 三个 Tab）
// 开发时通过 /api 代理访问 FastAPI，生产由 FastAPI 直接托管 dist
// ------------------------------------------------------------
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        client: fileURLToPath(new URL('./index.html', import.meta.url)),
        admin: fileURLToPath(new URL('./admin.html', import.meta.url))
      }
    }
  }
})
