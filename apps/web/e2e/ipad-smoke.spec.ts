/** P03 — iPad / 平板层 smoke。
 *
 * 不依赖真实栈：/api 路由全 stub（模式与 search.spec.ts 的 route.fulfill
 * 一致，fixture 形状与 src/__tests__/shell.test.tsx / reader.test.tsx 的
 * 最小契约相同）；认证走 basic 模式探测 stub（desktop-journeys 的栈语义
 * ——mode=basic 恒 authenticated，无账号/无 storageState 依赖）。
 *
 * 覆盖（仅 ipad-834 / ipad-1194 项目运行，见 test.skip）：
 * - ipad-834（834×1194 竖排）→ tablet 档：常驻侧栏（默认折叠 rail）、
 *   打开文章 → Reader 覆盖时间线、无底部导航岛、返回控件回列表；
 * - ipad-1194（1194×834 横排）→ ≥1024 desktop 档：三栏 + Reader 并排、
 *   无底部导航岛。
 */

import { expect, test } from '@playwright/test'

test.skip(
  ({ viewport }) => {
    const width = viewport?.width ?? 0
    return width !== 834 && width !== 1194
  },
  'iPad projects only（ipad-834 / ipad-1194）',
)

const SESSION = { mode: 'basic', authenticated: true }
const FEEDS = [
  { title: '平板冒烟源', feedUrl: 'https://ipad-smoke.example.com/feed.xml', category: null },
]

function entry(ref: string, title: string) {
  return {
    entryRef: ref,
    title,
    feedTitle: '平板冒烟源',
    author: null,
    url: null,
    publishedAt: '2026-09-01T00:00:00Z',
    read: false,
    starred: false,
  }
}

const ENTRIES = {
  items: [entry('ipad-smoke.1', '文章 平板冒烟 A'), entry('ipad-smoke.2', '文章 平板冒烟 B')],
  nextCursor: null,
}

const DETAIL = {
  entryRef: 'ipad-smoke.1',
  title: '文章 平板冒烟 A',
  feedTitle: '平板冒烟源',
  author: null,
  url: null,
  publishedAt: '2026-09-01T00:00:00Z',
  read: false,
  starred: false,
  contentText: '平板冒烟正文内容，用于 Reader 断言。',
  contentHtml: '<p>平板冒烟正文内容，用于 Reader 断言。</p>',
}

function json(body: unknown, status = 200) {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }
}

/** 注意：Playwright 后注册的 route 优先——先挂 catch-all 404（诚实降级，
 * 不阻塞 shell），再挂具体端点的最小 fixture。 */
async function stubApi(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/**', (route) =>
    route.fulfill(
      json({ error: { type: 'not_found', message: 'ipad-smoke stub' } }, 404),
    ),
  )
  await page.route('**/api/v1/auth/session**', (route) => route.fulfill(json(SESSION)))
  await page.route('**/api/v1/feeds**', (route) => route.fulfill(json(FEEDS)))
  await page.route('**/api/v1/entries?**', (route) => route.fulfill(json(ENTRIES)))
  await page.route('**/api/v1/entries/*', (route) => route.fulfill(json(DETAIL)))
}

test('ipad — 侧栏可见 / 打开文章 Reader 可见且无底栏', async ({ page }) => {
  await stubApi(page)
  await page.goto('/')

  // 平板层常驻侧栏（834 竖排默认折叠 rail，1194 横排为展开侧栏——同一
  // 导航语义，aria-label 共享「主导航」前缀）
  await expect(page.getByRole('navigation', { name: /主导航/ }).first()).toBeVisible()

  // 时间线行出现（与 rapid-selection 同一定位约定：行根 data-entry-ref
  // 内带文本的 aria-pressed 按钮）
  const titleButtons = page
    .locator('div[data-entry-ref] button[aria-pressed]')
    .filter({ visible: true })
    .filter({ hasText: /\S/ })
  await expect(titleButtons.first()).toBeVisible({ timeout: 15_000 })

  // 打开文章 → Reader 可见
  await titleButtons.first().click()
  await expect(page.locator('article h1')).toHaveText('文章 平板冒烟 A', {
    timeout: 15_000,
  })
  // 平板层无底部导航岛（compact 档专属）
  await expect(page.getByRole('navigation', { name: '底部导航' })).toHaveCount(0)
})

test('ipad-834 竖排 — 返回控件回到列表', async ({ page }) => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) !== 834, 'portrait only')
  await stubApi(page)
  await page.goto('/')

  const titleButtons = page
    .locator('div[data-entry-ref] button[aria-pressed]')
    .filter({ visible: true })
    .filter({ hasText: /\S/ })
  await expect(titleButtons.first()).toBeVisible({ timeout: 15_000 })

  await titleButtons.first().click()
  await expect(page.locator('article h1')).toBeVisible({ timeout: 15_000 })
  // 竖排：Reader 覆盖时间线（列表隐藏），顶栏出现返回控件（同移动契约）
  await expect(titleButtons.first()).not.toBeVisible()
  await page.getByRole('button', { name: '返回文章列表' }).click()
  await expect(titleButtons.first()).toBeVisible()
})
