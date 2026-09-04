/** 0018 浏览器流程 Flow A–E（Playwright 版，真实 production 栈）。
 *
 * Flow A  Operations：设置 → 账户与服务真实状态；
 * Flow B  RSSHub Control Center：typed 字段 / secret 写只读 / restartRequired；
 * Flow C  本地备份：创建 → job 状态 → 历史 → 刷新一致；
 * Flow E  恢复：预览 → 显式确认 → 执行 → 健康验证。
 * Flow D  WebDAV 见 webdav.spec.ts（一次性本地 WebDAV 服务）。
 */

import { expect, test } from '@playwright/test'
import { openSettingsCategory, visibleDialog } from './helpers'

test.describe.configure({ mode: 'serial' })

// Flow A/B/C/E 是桌面设置中心流程；移动端只做备份页触达 smoke
// （完整移动 journeys 属于 0019 C5）。
test.skip(({ viewport }) => (viewport?.width ?? 0) < 1024, 'desktop-only flows')

test('Flow A — 账户与服务显示真实依赖状态', async ({ page }) => {
  await page.goto('/')
  await openSettingsCategory(page, '账户与服务')
  const dialog = visibleDialog(page)

  // 真实状态行（数据来自 /api/v1/operations/status 的服务端探测）
  await expect(dialog.getByText('本地数据（lumi.sqlite）')).toBeVisible()
  await expect(dialog.getByText('正常').first()).toBeVisible()
  // smoke 栈：FreshRSS / RSSHub 都已配置且健康
  await expect(dialog.getByText('WebDAV 未配置').or(dialog.getByText('WebDAV 已配置'))).toBeVisible()
  // 页脚说明仍然诚实
  await expect(dialog.getByText(/状态来自服务端真实探测/)).toBeVisible()
  await page.keyboard.press('Escape')
})

test('Flow B — RSSHub 控制中心：字段编辑 / secret 写只读 / restartRequired', async ({ page }) => {
  await page.goto('/')
  await openSettingsCategory(page, 'RSSHub')
  const dialog = visibleDialog(page)

  // 运行时状态（真实探测）
  await expect(dialog.getByText('RSSHub 运行时')).toBeVisible()

  // typed 字段：CACHE_EXPIRE 是 number 输入（getByLabel 默认子串匹配，
  // 会同时命中「内容缓存过期」；exact 锁定唯一字段）
  const cacheExpire = dialog.getByLabel('路由缓存过期（分钟）', { exact: true })
  await expect(cacheExpire).toBeVisible()
  const original = await cacheExpire.inputValue()

  // secret 字段：password 型 + 不回显
  const accessKey = dialog.getByLabel('Access Key（secret）')
  if (await accessKey.count()) {
    await expect(accessKey).toHaveValue('')
    await expect(accessKey).toHaveAttribute('type', 'password')
  }

  // 编辑 → restartRequired 语义：保存后出现「需要重启 RSSHub 后生效」
  await cacheExpire.fill('777')
  await dialog.getByRole('button', { name: '保存更改' }).click()
  await expect(dialog.getByText(/项设置需要重启 RSSHub 后生效/)).toBeVisible()
  // 「标记为已应用」可用（operator 语义，Lumi 不自行重启）
  await expect(dialog.getByRole('button', { name: '标记为已应用' })).toBeEnabled()

  // 还原配置值（测试清理）
  await cacheExpire.fill(original)
  await dialog.getByRole('button', { name: '保存更改' }).click()
  await expect(dialog.getByRole('button', { name: /放弃更改/ })).toBeDisabled()
  await page.keyboard.press('Escape')
})

test('Flow C — 本地备份：创建 → job 完成 → 历史可见 → 刷新后一致', async ({ page }) => {
  await page.goto('/')
  await openSettingsCategory(page, '备份与恢复')
  const dialog = visibleDialog(page)

  await expect(dialog.getByText('备份概览')).toBeVisible()
  await dialog.getByRole('button', { name: /创建完整备份（本机）/ }).click()

  // job 完成后历史出现新条目（含文件名与大小）
  const history = dialog.locator('li', { hasText: /lumirss-\d{8}T\d{6}Z\.backup/ }).first()
  await expect(history).toBeVisible({ timeout: 30_000 })
  await expect(history.getByText(/已成功/)).toBeVisible()

  // 刷新页面后状态一致（服务端持久化，不是纯前端状态）
  await page.reload()
  await openSettingsCategory(page, '备份与恢复')
  await expect(
    visibleDialog(page).locator('li', { hasText: /lumirss-\d{8}T\d{6}Z\.backup/ }).first(),
  ).toBeVisible()
})

test('Flow E — 分阶段恢复向导：预览 → RESTORE 确认 → 执行 → 健康验证', async ({ page }) => {
  await page.goto('/')
  await openSettingsCategory(page, '备份与恢复')
  const dialog = visibleDialog(page)

  // 从历史第一个成功备份发起恢复
  const historyItem = dialog.locator('li', { hasText: /lumirss-\d{8}T\d{6}Z\.backup/ }).first()
  await expect(historyItem).toBeVisible({ timeout: 30_000 })
  await historyItem.getByRole('button', { name: /从此备份恢复/ }).click()

  const wizard = page.getByRole('dialog', { name: '从备份恢复' })
  await expect(wizard).toBeVisible()

  // 阶段 1：来源选择（本机备份列表）
  await wizard.locator('button', { hasText: /lumirss-\d{8}T\d{6}Z\.backup/ }).first().click()

  // 阶段 2：预览（checksum + manifest 校验通过）
  await expect(wizard.getByText(/checksum（SHA-256）与 manifest 均已验证/)).toBeVisible()

  // 阶段 3：显式确认（输入 RESTORE 之前按钮禁用）
  await wizard.getByRole('button', { name: /继续恢复…/ }).click()
  const confirmInput = wizard.getByLabel('输入 RESTORE 以确认恢复')
  const executeButton = wizard.getByRole('button', { name: /执行恢复/ })
  await expect(executeButton).toBeDisabled()
  await confirmInput.fill('RESTORE')
  await expect(executeButton).toBeEnabled()
  await executeButton.click()

  // 阶段 4：结果（本地数据恢复 + 健康检查通过 + 安全备份 ID）
  await expect(wizard.getByText(/恢复完成/)).toBeVisible()
  await expect(wizard.getByText(/恢复前安全备份/)).toBeVisible()
  await expect(wizard.getByText(/健康检查通过/)).toBeVisible()
})

test('移动视口 — 备份页无横向溢出且触达良好', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  // 移动端路径：打开导航抽屉 → 品牌区设置按钮 → MobileSettingsScreen
  await page.getByRole('button', { name: '打开导航' }).click()
  await page.getByRole('button', { name: '打开设置' }).click()
  const screen = page.getByRole('dialog', { name: '设置' })
  await expect(screen).toBeVisible()
  await screen.getByRole('button', { name: '备份与恢复' }).click()
  await expect(screen.getByText('备份概览')).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
})
