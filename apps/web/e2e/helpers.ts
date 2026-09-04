/** E2E helpers — settings 导航、API 等待、视口无关的操作封装。
 * 只使用页面可见语义（role/name），不依赖实现类名。 */

import { expect, type Page } from '@playwright/test'

/** 打开设置中心并进入某个分类。 */
export async function openSettingsCategory(page: Page, name: string | RegExp) {
  await page.getByRole('button', { name: '打开设置' }).click()
  const dialog = visibleDialog(page)
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name }).click()
}

/** 当前可见的设置对话框（桌面 Modal 与移动设置屏都在 DOM 中，
 * 必须按可见性过滤，否则 strict mode 冲突）。 */
export function visibleDialog(page: Page) {
  return page.getByRole('dialog').filter({ visible: true }).first()
}

/** 关闭设置中心（Escape）。 */
export async function closeSettings(page: Page) {
  await page.keyboard.press('Escape')
}

/** 等待应用完成首次数据加载（侧栏出现订阅区）。 */
export async function waitForAppReady(page: Page) {
  await expect(page.getByRole('button', { name: '打开设置' })).toBeVisible()
}

/** 校验页面没有横向溢出（移动端硬门）。 */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    return document.documentElement.scrollWidth - document.documentElement.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(1)
}
