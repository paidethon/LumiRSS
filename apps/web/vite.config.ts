/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// 构建溯源（关于页展示，与 BFF GET /api/v1/version 对照判断 Web/BFF 版本错配）：
// Docker/CI 构建时通过 VITE_GIT_COMMIT 注入；本地 dev 留空。
const gitCommit = process.env.VITE_GIT_COMMIT ?? ''

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    'import.meta.env.VITE_GIT_COMMIT': JSON.stringify(gitCommit),
  },
  server: {
    proxy: {
      // 开发期代理：浏览器同源请求 /api/*，由 Vite 转发给 FastAPI BFF。
      // 未来生产环境由 Caddy 做同样的 /api 反代，React 代码不变。
      '/api': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    // e2e/ 归 Playwright（playwright.config.ts），vitest 不收集
    exclude: ['**/node_modules/**', 'e2e/**', 'dist/**'],
  },
})
