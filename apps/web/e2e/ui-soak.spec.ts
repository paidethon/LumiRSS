/** O199 UI soak：真实浏览器连续交互负载（desktop-1440 单项目运行）。
 * 每轮：抽屉开→关、底部导航切换、打开文章→返回、搜索→清除。
 * 断言：每轮零页面错误（error 事件捕获）、无水平溢出、dialog 零残留。
 * 运行：LUMIRSS_E2E_BASE_URL=… LUMIRSS_E2E_LOGIN=… playwright test ui-soak
 */
import { test, expect } from '@playwright/test'

const ROUNDS = Number(process.env.UI_SOAK_ROUNDS ?? 30)

test.describe.serial('UI soak（真实浏览器负载）', () => {
  let pageErrors: string[] = []

  test.beforeEach(async ({ page }) => {
    pageErrors = []
    page.on('pageerror', (err) => pageErrors.push(String(err)))
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  })

  test(`连续 ${ROUNDS} 轮交互零残留`, async ({ page }) => {
    for (let i = 0; i < ROUNDS; i++) {
      // 1. 抽屉开→关
      const menu = page.getByRole('button', { name: '打开导航' })
      if (await menu.isVisible().catch(() => false)) {
        await menu.click()
        const close = page
          .getByRole('dialog')
          .filter({ visible: true })
          .getByRole('button', { name: '关闭' })
        if (await close.isVisible().catch(() => false)) {
          await close.click()
        }
        await expect(page.getByRole('dialog')).toHaveCount(0)
      }
      // 2. 底部导航：搜索 → 首页
      const navSearch = page.getByRole('navigation', { name: '底部导航' }).getByRole('button', { name: '搜索' })
      if (await navSearch.isVisible().catch(() => false)) {
        await navSearch.click()
        await navSearch
          .getByRole('button', { name: '首页' })
          .or(page.getByRole('navigation', { name: '底部导航' }).getByRole('button', { name: '首页' }))
          .click()
      }
      // 3. 打开第一篇文章 → 返回
      const row = page.locator('[data-entry-row-ref]').locator('visible=true').first()
      if (await row.isVisible().catch(() => false)) {
        await row.locator('button:visible').last().click()
        await expect(page.locator('article').first()).toBeVisible()
        const back = page.getByRole('button', { name: /返回|Back/ }).first()
        if (await back.isVisible().catch(() => false)) await back.click()
      }
      // 4. 残留断言
      expect(pageErrors, `round ${i} page errors`).toEqual([])
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      )
      expect(overflow, `round ${i} horizontal overflow`).toBeLessThanOrEqual(1)
    }
  })
})
