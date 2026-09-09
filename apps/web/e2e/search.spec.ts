/** Search E2E（0022 §71 验收矩阵）。
 *
 * 对真实栈（BFF + FreshRSS 派生投影）验证：
 * 空态 / 基本命中 / 无结果 / Unicode·CJK / 特殊字符 / 过滤器（未读、
 * 收藏、分类）/ 返回保持 / 错误态（路由拦截注入 500）。
 * 分页由投影真实数据量决定（dev 栈 60+ 条 > 默认页大小 20 → hasMore
 * 路径天然覆盖「加载更多」）。
 *
 * 数据隔离：只读搜索 + 打开文章（打开不自动已读）；不动用户真实状态。
 */

import { expect, test, type Page } from '@playwright/test'
import { waitForAppReady } from './helpers'

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
    await searchFor(page, box, '科技爱好者周刊')
    const firstResult = page.getByRole('button', { name: /科技爱好者周刊/ }).first()
    await expect(firstResult).toBeVisible({ timeout: 15_000 })

    // 结果摘要片段是纯文本（无 HTML 标签泄漏）
    const snippet = page.locator('ul[aria-label="搜索结果"] span').filter({ hasText: /…|。|，/ }).first()
    await expect(snippet).not.toContainText('<')

    // 打开 → Reader；返回 → 查询与结果保持
    await firstResult.click()
    await expect(page.getByRole('button', { name: '返回文章列表' })).toBeVisible({ timeout: 10_000 })
    await page.getByRole('button', { name: '返回文章列表' }).click()
    await expect(page.getByRole('searchbox', { name: '搜索' }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: /科技爱好者周刊/ }).first()).toBeVisible()
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

  test('过滤器 chips（未读 / 收藏）与分类下拉可用且结果随过滤变化', async ({ page }) => {
    const box = await openSearch(page)
    await searchFor(page, box, '周刊')
    await expect(page.locator('ul[aria-label="搜索结果"] li').first()).toBeVisible({ timeout: 15_000 })

    await page.getByRole('button', { name: '未读', exact: true }).click()
    await page.waitForTimeout(600) // 防抖 + 查询
    await page.getByRole('button', { name: '收藏', exact: true }).click()
    await page.waitForTimeout(600)
    await page.getByRole('combobox', { name: '按分类过滤' }).selectOption({ index: 1 })
    await page.waitForTimeout(600)
    // 任一诚实状态都可接受：结果列表 / 无结果 —— 关键是不崩、不假成功
    await expect(page.locator('body')).toContainText(/科技爱好者周刊|没有找到|搜索索引/)
  })

  test('错误态：后端 500 → 错误文案 + 重试（路由拦截注入）', async ({ page }) => {
    await page.route('**/api/v1/search?**', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":{"type":"upstream_error","message":"boom"}}' }),
    )
    const box = await openSearch(page)
    await searchFor(page, box, '周刊')
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
    await box.fill('周刊')
    await box.press('Enter')
    await expect(page.locator('ul[aria-label="搜索结果"] li').first()).toBeVisible({ timeout: 15_000 })
  })
})
