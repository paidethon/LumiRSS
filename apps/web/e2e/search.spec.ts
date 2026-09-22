/** Search E2E（0022 §71 验收矩阵）。
 *
 * 对真实栈（BFF + FreshRSS 派生投影）验证：
 * 空态 / 基本命中 / 无结果 / Unicode·CJK / 特殊字符 / 过滤器（未读、
 * 收藏、分类）/ 返回保持 / 错误态（路由拦截注入 500）。
 *
 * 数据契约（Q-P2-36 治理）：查询词使用 Gate 8 fixture 的确定内容
 * （api-source e2e-json-* → 「sqlite-vec 发布 1.0」），不再依赖开发栈
 * 恰好订阅过什么。前置：`e2e/stack/run-smoke.sh all` 已在该栈上运行
 * （订阅 + actualize 由 smoke 完成）。
 *
 * 数据隔离：只读搜索 + 打开文章（打开不自动已读）；不动用户真实状态。
 */

import { expect, test, type Page } from '@playwright/test'
import { waitForAppReady } from './helpers'

/** Gate 8 fixture 条目的确定词（标题 + 正文都含；CJK 与 ASCII 各测一）。 */
const SEEDED_ASCII = 'sqlite-vec'
const SEEDED_CJK = '发布'

async function openSearch(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '搜索', exact: true }).first().click()
  const box = page.getByRole('searchbox', { name: '搜索' }).first()
  await expect(box).toBeVisible()
  return box
}

async function searchFor(page: Page, box: ReturnType<Page['getByRole']>, query: string) {
  await box.fill(query)
  await box.press('Enter')
}

test.describe('搜索 — 桌面（1440）', () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) < 1024, 'desktop-only')

  test.beforeEach(async ({ context }) => {
    // 隔离 localStorage（搜索历史跨运行残留会改变空态形态）
    await context.addInitScript(() => localStorage.clear())
  })
  test('空查询 → 引导空态；无结果 → 诚实无结果（不冒充）', async ({ page }) => {
    await openSearch(page)
    await expect(page.getByText('搜索你的全部订阅')).toBeVisible()
  })

  test('基本命中：真实条目标题出现在结果里，可打开 Reader，返回后状态保持', async ({ page }) => {
    const box = await openSearch(page)
    await searchFor(page, box, SEEDED_ASCII)
    const firstResult = page.getByRole('button', { name: new RegExp(SEEDED_ASCII) }).first()
    await expect(firstResult).toBeVisible({ timeout: 15_000 })

    // 结果摘要片段是纯文本（无 HTML 标签泄漏）
    const snippet = page.locator('ul[aria-label="搜索结果"] span').filter({ hasText: /…|。|，/ }).first()
    await expect(snippet).not.toContainText('<')

    // 打开 → Reader（桌面三栏：Reader 出现在右栏；「返回文章列表」是
    // <1024 的移动头部控件，1440 下不存在）。Escape 清空选择 → 查询与
    // 结果保持。
    await firstResult.click()
    await expect(page.locator('article').first()).toBeVisible({ timeout: 10_000 })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('searchbox', { name: '搜索' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(SEEDED_ASCII) }).first()).toBeVisible()
  })

  test('无结果 + Unicode/特殊字符查询不崩（% _ 引号 括号）', async ({ page }) => {
    const box = await openSearch(page)
    for (const query of ['xyzzyplugh12345', '100%', 'a_b', '"引号"', '(括号)']) {
      await searchFor(page, box, query)
      await expect(
        page.getByText(new RegExp(`没有找到与「${query}」|没有找到与`)).first(),
      ).toBeVisible({ timeout: 10_000 })
    }
  })

  test('过滤器 chips（未读 / 收藏）与分类下拉真实改变查询与结果', async ({ page }) => {
    const box = await openSearch(page)
    await searchFor(page, box, SEEDED_ASCII)
    await expect(page.locator('ul[aria-label="搜索结果"] li').first()).toBeVisible({ timeout: 15_000 })
    const baselineRows = await page.locator('ul[aria-label="搜索结果"] li').count()

    // Q-P1-12：断言 chip 真正触发带过滤参数的新查询（旧断言只检查
    // body 含任意文案——no-op 实现照样通过），并用行数变化验证结果
    // 确实随过滤变化（未读 ⊆ 全部；数据集含已读条目）。
    // 搜索结果列表内的过滤 chip（侧栏信息来源区也有同名 chip，必须限定作用域）
    const unreadRequest = page.waitForRequest(
      (req) => req.url().includes('/api/v1/search') && req.url().includes('state=unread'),
    )
    await page.getByLabel('搜索范围').getByRole('button', { name: '未读', exact: true }).click()
    const unreadReq = await unreadRequest
    // 新查询完成后列表重渲染（行数 ≤ 基线，且不出现加载骨架闪烁假象）
    await expect(page.locator('ul[aria-label="搜索结果"] li').first()).toBeVisible({ timeout: 15_000 })
    const unreadRows = await page.locator('ul[aria-label="搜索结果"] li').count()
    expect(unreadRows).toBeLessThanOrEqual(baselineRows)

    const starredRequest = page.waitForRequest(
      (req) => req.url().includes('/api/v1/search') && req.url().includes('favorite=true'),
    )
    await page.getByLabel('搜索范围').getByRole('button', { name: '收藏', exact: true }).click()
    await starredRequest

    const categoryRequest = page.waitForRequest(
      (req) => req.url().includes('/api/v1/search') && req.url().includes('categoryId='),
    )
    await page.getByRole('combobox', { name: '按分类过滤' }).selectOption({ index: 1 })
    await categoryRequest
    // 过滤后的诚实状态（有结果或无结果都合法——但查询必须已重发）。
    await expect(page.locator('body')).toContainText(new RegExp(`${SEEDED_ASCII}|没有找到|搜索索引`))
    void unreadReq
  })

  test('错误态：后端 500 → 错误文案 + 重试（路由拦截注入）', async ({ page }) => {
    await page.route('**/api/v1/search?**', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":{"type":"upstream_error","message":"boom"}}' }),
    )
    const box = await openSearch(page)
    await searchFor(page, box, SEEDED_ASCII)
    await expect(page.getByText('搜索失败')).toBeVisible()
    await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  })
})

test.describe('搜索 — 移动（390）', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

  test.beforeEach(async ({ context }) => {
    await context.addInitScript(() => localStorage.clear())
  })

  test('底栏进搜索 → CJK 查询 → 单列结果 → 输入框不溢出', async ({ page }) => {
    await page.goto('/')
    await waitForAppReady(page)
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    const box = page.getByRole('searchbox', { name: '搜索' }).first()
    await expect(box).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    )
    expect(overflow).toBe(false)
    await box.fill(SEEDED_CJK)
    await box.press('Enter')
    await expect(page.locator('ul[aria-label="搜索结果"] li').first()).toBeVisible({ timeout: 15_000 })
  })
})
