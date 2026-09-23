/** Playwright E2E — 0019 C3（0018 B8 起使用）。
 *
 * 两层：
 * - product journeys（确定性 UI 流程）：对 baseURL 栈运行，测试数据隔离、
 *   无真实账号 / 无真实 AI Key / 无生产凭据；
 * - production smoke：对 docker-compose.prod 栈验证关键路径与健康。
 *
 * 运行前必须有一个可用栈：`pnpm test:e2e` 读取 LUMIRSS_E2E_BASE_URL
 * （默认 http://127.0.0.1，对应 docker-compose.prod 的 web/Caddy 发布入口
 * 80/443；若你的部署用 HTTPS 或其它端口，用 LUMIRSS_E2E_BASE_URL 覆盖。
 * CI 静态冒烟用 http://127.0.0.1:4173 的 vite preview，见下方 ciStatic）。
 * 报告 / trace / 截图全部落在 gitignored 的 test-results/ 与
 * playwright-report/ 目录。
 */

import { defineConfig } from '@playwright/test'

const baseURL = process.env.LUMIRSS_E2E_BASE_URL ?? 'http://127.0.0.1'

// CI 静态冒烟模式：自动启动 vite preview（无后端 API，验证降级态 UI）。
// 本地/全栈跑法不启用（栈由 docker compose 提供）。
const ciStatic = process.env.LUMIRSS_CI_STATIC === '1'
// session 模式栈的预登录（Round 2 审计发现：journeys 只适配过 basic 栈，
// session 栈上浏览器停在登录页）。设置口令 → globalSetup 登录一次，
// storageState 注入全部 context；不设置（basic / CI 静态）行为不变。
const sessionLogin = process.env.LUMIRSS_E2E_LOGIN

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
  ...(sessionLogin ? { globalSetup: './e2e/global-setup.ts' } : {}),
  use: {
    baseURL,
    ...(sessionLogin
      ? { storageState: './e2e/.auth/state.json' }
      : {}),
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
    // P03 平板层：iPad 竖排（834×1194 → tablet 档，竖排默认折叠 rail +
    // Reader 覆盖列表）与横排（1194×834 → ≥1024 desktop 档三栏）。
    // 触屏 + 移动 UA + deviceScaleFactor 2 对齐真机；Chromium 触摸仿真
    // 可跑，真机 Safari 表现仍需人工验证（同 webkit-mobile 的边界）。
    // 只跑 ipad-smoke：既有 journeys 按手机/桌面二分断言（mobile-journeys
    // 的底栏断言 / desktop journeys 的全量流程均未覆盖平板 shell），
    // 平板 journeys 扩量属后续里程碑。
    {
      name: 'ipad-834',
      testIgnore: /^(?!.*ipad-smoke)/,
      use: {
        viewport: { width: 834, height: 1194 },
        deviceScaleFactor: 2,
        hasTouch: true,
        isMobile: true,
        userAgent:
          'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E Safari/604.1',
      },
    },
    {
      name: 'ipad-1194',
      testIgnore: /^(?!.*ipad-smoke)/,
      use: {
        viewport: { width: 1194, height: 834 },
        deviceScaleFactor: 2,
        hasTouch: true,
        isMobile: true,
        userAgent:
          'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E Safari/604.1',
      },
    },
    // 2026-09 移动端专项：WebKit 手机旅程（iPhone 类视口；真机表现仍需
    // 人工验证——自动化 WebKit 不等于真机 Safari）。宿主缺 GTK4/GStreamer
    // 库时此项目会在启动时报错（sudo 安装依赖见验收记录的环境阻塞节）。
    {
      name: 'webkit-mobile-390',
      testIgnore: /desktop-journeys|a11y|webdav|print-view/,
      use: {
        browserName: 'webkit',
        viewport: { width: 390, height: 844 },
        hasTouch: true,
        isMobile: true,
      },
    },
  ],
})
