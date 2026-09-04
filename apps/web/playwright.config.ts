/** Playwright E2E — 0019 C3（0018 B8 起使用）。
 *
 * 两层：
 * - product journeys（确定性 UI 流程）：对 baseURL 栈运行，测试数据隔离、
 *   无真实账号 / 无真实 AI Key / 无生产凭据；
 * - production smoke：对 docker-compose.prod 栈验证关键路径与健康。
 *
 * 运行前必须有一个可用栈：`pnpm test:e2e` 读取 LUMIRSS_E2E_BASE_URL
 * （默认 http://127.0.0.1:18080，对应 docker-compose.prod 的 smoke 入口）。
 * 报告 / trace / 截图全部落在 gitignored 的 test-results/ 与
 * playwright-report/ 目录。
 */

import { defineConfig } from '@playwright/test'

const baseURL = process.env.LUMIRSS_E2E_BASE_URL ?? 'http://127.0.0.1:18080'

// CI 静态冒烟模式：自动启动 vite preview（无后端 API，验证降级态 UI）。
// 本地/全栈跑法不启用（栈由 docker compose 提供）。
const ciStatic = process.env.LUMIRSS_CI_STATIC === '1'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  ...(ciStatic
    ? {
        webServer: {
          command: 'pnpm preview --host 127.0.0.1 --port 4173 --strictPort',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: false,
          timeout: 60_000,
        },
      }
    : {}),
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 10_000,
    locale: 'zh-CN',
  },
  projects: [
    { name: 'desktop-1920', use: { viewport: { width: 1920, height: 1080 } } },
    { name: 'desktop-1440', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile-430', use: { viewport: { width: 430, height: 932 }, hasTouch: true, isMobile: true } },
    { name: 'mobile-390', use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
    { name: 'mobile-375', use: { viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true } },
  ],
})
