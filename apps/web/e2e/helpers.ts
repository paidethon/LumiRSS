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

/** 打开导航抽屉 → 进入移动设置页。设置入口在抽屉内的 SidebarHeader，
 * 移动端没有绕过抽屉的直达路径。 */
export async function openMobileSettings(page: Page, category?: string) {
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.getByRole('button', { name: '打开设置' }).click()
  const screen = page.getByRole('dialog', { name: '设置' })
  await expect(screen).toBeVisible()
  if (category) {
    await screen.getByRole('button', { name: category }).click()
  }
  return screen
}

/** 关闭移动设置。设置 Sheet 打开时导航抽屉仍在其下（分层模态），
 * Escape 一次只关最顶层；快速连按可能撞上退出动画，所以循环关到
 * 主页干净态（☰ 触发器 expanded=false）为止。用 CSS 定位——抽屉
 * 打开时触发器被遮罩 aria-hidden，role 定位会空等超时。 */
export async function closeMobileSettings(page: Page) {
  const nav = page.locator('button[aria-label="打开导航"]')
  for (let i = 0; i < 6; i++) {
    if ((await nav.getAttribute('aria-expanded')) === 'false') break
    await page.keyboard.press('Escape')
    await page.waitForTimeout(150)
  }
  await expect(nav).toHaveAttribute('aria-expanded', 'false')
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
