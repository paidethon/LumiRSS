/** E2E helpers — settings 导航、API 等待、视口无关的操作封装。
 * 只使用页面可见语义（role/name），不依赖实现类名。 */

import { execFileSync } from 'node:child_process'
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

/** 等待应用完成首次数据加载（桌面：设置入口出现；移动：导航入口出现——
 * 打开设置本身在抽屉内，要等打开导航后二次点击）。 */
export async function waitForAppReady(page: Page) {
  await expect(
    page
      .getByRole('button', { name: '打开设置' })
      .or(page.getByRole('button', { name: '打开导航' }))
      .first(),
  ).toBeVisible()
}

/** 确保 BFF 侧存在 default AI key——AI journeys 自建前置（幂等）。
 * BFF 调任何 OpenAI 兼容端点都要求非空 key（Bearer 头），mock 服务
 * 不校验其值。只在尚未配置时经 write-only API 写入一个显式假 key
 * （sk- 前缀同时让「key 不回显」断言有真实形状可校验）——绝不覆盖
 * 已存在的真实用户 key。 */
export async function ensureMockDefaultAiKey(page: Page) {
  const status = await (await page.request.get('/api/v1/settings/ai')).json()
  if (status.defaultKeyConfigured) return
  const resp = await page.request.put('/api/v1/settings/ai/key', {
    data: { value: 'sk-e2e-mock-key-not-a-real-credential' },
  })
  expect(resp.status()).toBe(204)
}

/** 校验页面没有横向溢出（移动端硬门）。 */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    return document.documentElement.scrollWidth - document.documentElement.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(1)
}

/** 容器内 BFF/FreshRSS 访问宿主机 mock 服务要经 docker 网桥网关。子网
 * 随网络重建漂移（曾硬编码 172.19.0.1，网络重建后过期——J4/M3 全红
 * 的根因），所以运行时从 lumirss compose 网络读真实网关；docker CLI
 * 不可用时回退 LUMIRSS_E2E_BRIDGE_IP，再回退宿主机回环（宿主机 BFF
 * 拓扑，mock 绑定 0.0.0.0 时网关地址同样可达）。 */
export function resolveBridgeIp(): string {
  const explicit = process.env.LUMIRSS_E2E_BRIDGE_IP
  if (explicit) return explicit
  try {
    const names = execFileSync('docker', ['network', 'ls', '--format', '{{.Name}}'], {
      encoding: 'utf8',
    })
      .split('\n')
      .map((n) => n.trim())
      .filter((n) => n === 'lumirss_default' || n.toLowerCase().includes('lumirss'))
    for (const name of names) {
      const info = JSON.parse(
        execFileSync('docker', ['network', 'inspect', name], { encoding: 'utf8' }),
      ) as Array<{ IPAM?: { Config?: Array<{ Gateway?: string }> } }>
      const gateway = info[0]?.IPAM?.Config?.[0]?.Gateway
      if (gateway) return gateway
    }
  } catch {
    // docker CLI 不可用 / 无匹配网络 → 走回退
  }
  return '127.0.0.1'
}
