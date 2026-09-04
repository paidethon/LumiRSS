/** 移动端 smoke — 备份页在移动 shell 的触达路径与无横向溢出。
 * 完整移动 journeys 属于 0019 C5。 */

import { expect, test } from '@playwright/test'

test.describe('移动端 smoke（0018）', () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) >= 1024, 'mobile-only')

  test('移动视口 — 备份页无横向溢出且触达良好', async ({ page }) => {
    await page.goto('/')
    // 移动端路径：打开导航抽屉 → 品牌区设置按钮 → MobileSettingsScreen
    await page.getByRole('button', { name: '打开导航' }).click()
    await page.getByRole('button', { name: '打开设置' }).click()
    const screen = page.getByRole('dialog', { name: '设置' })
    await expect(screen).toBeVisible()
    await screen.getByRole('button', { name: '备份与恢复' }).click()
    await expect(screen.getByText('备份概览')).toBeVisible()
    await expect(screen.getByText('备份历史')).toBeVisible()
    await expect(screen.getByText('WebDAV 远程备份')).toBeVisible()
    await expect(screen.getByText(/配置迁移/)).toBeVisible()

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
