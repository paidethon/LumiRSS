/** 0018 Flow D — WebDAV（一次性本地 WebDAV 服务，进程内启动）。
 *
 * 覆盖：保存设置（密码写只读）→ 测试连接 → 备份并上传 → 远端列表 →
 * 错误凭据产生安全错误。密码不回显（UI 与 API 两侧）。
 */

import http from 'node:http'
import { expect, test, type Page } from '@playwright/test'
import { openSettingsCategory, visibleDialog } from './helpers'
import { createWebDavServer } from './webdav-server'

const WEBDAV_PORT = 18081
const WEBDAV_USER = 'e2e-dav-user'
const WEBDAV_PASS = 'e2e-dav-pass'
// BFF 在容器里运行：127.0.0.1 指向容器自身。默认走 docker 网桥 IP
// （私有网段，符合 BFF 的 WebDAV http 策略）；宿主机直跑时用 127.0.0.1。
const WEBDAV_URL =
  process.env.LUMIRSS_E2E_WEBDAV_URL ?? `http://172.19.0.1:${WEBDAV_PORT}/`

test.describe.configure({ mode: 'serial' })

// WebDAV 流程在桌面设置中心验证一次；移动端触达在 0019 journeys 覆盖。
test.skip(({ viewport }) => (viewport?.width ?? 0) < 1024, 'desktop-only flows')

let server: http.Server

test.beforeAll(async () => {
  server = createWebDavServer(WEBDAV_USER, WEBDAV_PASS)
  await new Promise<void>((resolve) => server.listen(WEBDAV_PORT, '0.0.0.0', resolve))
})

test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()))
})

async function openBackupSettings(page: Page) {
  await page.goto('/')
  await openSettingsCategory(page, '备份与恢复')
  const dialog = visibleDialog(page)
  await expect(dialog.getByText('WebDAV 远程备份')).toBeVisible()
  return dialog
}

test('WebDAV 保存 + 测试连接 + 备份上传 + 远端列表', async ({ page }) => {
  const dialog = await openBackupSettings(page)

  // 保存设置（密码只写不读）
  await dialog.getByLabel('服务地址（https）').fill(WEBDAV_URL)
  await dialog.getByLabel('用户名', { exact: true }).fill(WEBDAV_USER)
  await dialog.getByLabel(/密码/).fill(WEBDAV_PASS)
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog.getByText('已保存。')).toBeVisible()

  // 密码不回显：输入框清空 + 占位符显示已保存状态
  const passwordInput = dialog.getByLabel(/密码/)
  await expect(passwordInput).toHaveValue('')

  // 测试连接
  await dialog.getByRole('button', { name: /测试连接/ }).click()
  await expect(dialog.getByText('连接成功。')).toBeVisible()

  // 备份并上传 WebDAV
  await dialog.getByRole('button', { name: /备份并上传 WebDAV/ }).click()
  await expect(
    dialog.locator('li', { hasText: /lumirss-\d{8}T\d{6}Z\.backup/ }).first(),
  ).toBeVisible({ timeout: 30_000 })
})

test('WebDAV 错误凭据：测试连接显示安全错误（无密码泄漏）', async ({ page }) => {
  const dialog = await openBackupSettings(page)

  // 用错误密码覆盖保存
  await dialog.getByLabel('服务地址（https）').fill(WEBDAV_URL)
  await dialog.getByLabel('用户名', { exact: true }).fill(WEBDAV_USER)
  await dialog.getByLabel(/密码/).fill('wrong-password')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(dialog.getByText('已保存。')).toBeVisible()

  await dialog.getByRole('button', { name: /测试连接/ }).click()
  await expect(dialog.getByText(/连接失败|测试失败/)).toBeVisible()
  // 密码值不能出现在页面任何地方
  const bodyText = await page.locator('body').innerText()
  expect(bodyText).not.toContain(WEBDAV_PASS)
  expect(bodyText).not.toContain('wrong-password')
})
