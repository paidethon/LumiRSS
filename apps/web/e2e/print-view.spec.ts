/** F24 清洁打印视图 — print 媒体模拟的布局验收。
 *
 * emulateMedia('print') 后：导航（header/nav/aside）、时间线列、分隔
 * 条、按钮与目录不显示（display:none 的元素同时离开可访问性树，
 * getByRole 计数为 0）；正文容器（.article-content）保留可见。
 * 对 compose 栈运行（LUMIRSS_E2E_BASE_URL），CI 静态构建自动跳过。 */

import { expect, test } from '@playwright/test'

test.skip(process.env.LUMIRSS_CI_STATIC === '1', '需要 compose 栈（有 API）')

test('print 媒体下隐藏导航与交互控件，正文保留', async ({ page }) => {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.emulateMedia({ media: 'print' })

  await expect(page.getByRole('navigation')).toHaveCount(0)
  await expect(page.getByRole('banner')).toHaveCount(0)
  await expect(page.getByRole('button')).toHaveCount(0)
  await expect(page.locator('.article-content').first()).toBeAttached()

  await page.emulateMedia({ media: 'screen' })
  await expect(page.getByRole('navigation').first()).toBeAttached()
})
