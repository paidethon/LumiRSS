import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

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
    // 每个 worker 都是一个完整 jsdom 环境 + 全量模块图；不设上限时
    // vitest 会按逻辑核数（本机 20）全开，多进程并发（构建/后端测试
    // 同时运行）下事件循环饥饿会让 waitFor 超时（历史 scroll-mark-unread
    // / mobile-reader 抖动）。封顶后单文件仍能拿到稳定 CPU 配额。
    // （vitest 4 移除了 poolOptions，worker 上限统一走 maxWorkers。）
    maxWorkers: 8,
  },
})
