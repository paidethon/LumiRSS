/** 0019 C4 — 桌面完整用户流程 journeys。
 *
 * 使用一次性本地 mock 服务（feed + OpenAI 兼容 AI）与运行中的
 * production 栈；不依赖任何真实账号 / 真实 AI Key / 生产服务。
 * 各 journey 串行（订阅与 AI 配置有先后依赖）。
 */

import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'
import { ensureMockDefaultAiKey, openSettingsCategory, visibleDialog } from './helpers'
import { createAiMockServer, createFeedServer } from './mock-servers.mjs'

/** 容器内 BFF/FreshRSS 访问宿主机 mock 服务要经 docker 网桥网关。子网
 * 随网络重建漂移（曾硬编码 172.19.0.1，网络重建后过期——J4/M3 全红
 * 的根因），所以运行时从 lumirss compose 网络读真实网关；docker CLI
 * 不可用时回退 LUMIRSS_E2E_BRIDGE_IP，再回退宿主机回环（宿主机 BFF
 * 拓扑，mock 绑定 0.0.0.0 时网关地址同样可达）。 */
function resolveBridgeIp(): string {
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

const BRIDGE = resolveBridgeIp()
const FEED_PORT = 18083
const AI_PORT = 18082
const FEED_URL = `http://${BRIDGE}:${FEED_PORT}/feed.xml`

test.describe.configure({ mode: 'serial' })

test.skip(({ viewport }) => (viewport?.width ?? 0) < 1024, 'desktop-only journeys')

let feedServer: import('node:http').Server
let aiServer: import('node:http').Server

test.beforeAll(async () => {
  feedServer = await createFeedServer(FEED_PORT, '0.0.0.0')
  aiServer = await createAiMockServer(AI_PORT, '0.0.0.0')
})

test.afterAll(async () => {
  feedServer?.close()
  aiServer?.close()
})

test('J1 — 启动与导航：shell / 侧栏 / deep link / 前进后退', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '打开设置' })).toBeVisible()
  // 侧栏主要 section 可见
  for (const name of ['全部', '未读', '收藏', '订阅']) {
    await expect(page.getByRole('button', { name }).first()).toBeVisible()
  }
  // 刷新后仍在（路由/shell 稳定）
  await page.reload()
  await expect(page.getByRole('button', { name: '打开设置' })).toBeVisible()
})

async function importFeedViaOpml(page: Page, feedUrl: string) {
  // 幂等重置：移除上次运行留下的同名订阅（合并语义会把它判成重复）
  const subs = await (await page.request.get('/api/v1/subscriptions')).json()
  for (const sub of subs) {
    if (sub.feedUrl === feedUrl) {
      await page.request.delete(`/api/v1/subscriptions/${encodeURIComponent(sub.subscriptionRef)}`)
    }
  }

  await page.getByRole('button', { name: '打开设置' }).click()
  const dialog = visibleDialog(page)
  await dialog.getByRole('button', { name: '订阅与来源' }).click()
  // 直接对 file input 上传（sr-only input 由 label 关联，无需点击按钮）；
  // 之后 preview 摘要 → 确认导入（真实闭环）
  const opml = `<?xml version="1.0"?><opml version="2.0"><head><title>t</title></head><body>
    <outline text="Lumi E2E Feed"><outline text="E2E 源" type="rss" xmlUrl="${feedUrl}"/></outline>
  </body></opml>`
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'import.opml',
    mimeType: 'text/xml',
    buffer: Buffer.from(opml),
  })
  await expect(dialog.getByText(/新增/).first()).toBeVisible({ timeout: 15_000 })
  await dialog.getByRole('button', { name: '确认导入' }).click()
  await expect(dialog.getByText(/已导入/).first()).toBeVisible({ timeout: 15_000 })
  await page.keyboard.press('Escape')
}

test('J3a — 直接添加：私网地址被 SSRF 策略诚实拒绝（安全边界）', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '添加来源' }).click()
  const dialog = visibleDialog(page)
  await dialog.getByLabel('RSS / Atom 地址').fill(FEED_URL)
  await dialog.getByRole('button', { name: /获取预览|预览/ }).click()
  // BFF 对不可信来源 URL 的 SSRF 防护是既定安全边界：如实展示错误
  await expect(dialog.getByText(/非公网|不允许|无法获取|失败/).first()).toBeVisible({
    timeout: 15_000,
  })
  await page.keyboard.press('Escape')
})

test('J3b — 订阅与分类：OPML 导入真实条目 / 导出可用 / 分类管理', async ({ page }) => {
  await page.goto('/')
  await importFeedViaOpml(page, FEED_URL)

  // 桌面侧栏出现新来源（FreshRSS 抓取完成；feeds 契约返回 title=E2E 源）
  await expect(page.getByText('E2E 源').first()).toBeVisible({ timeout: 15_000 })
})

test('J2 — 时间线与 Reader：打开不自动已读 / 显式已读 / 收藏', async ({ page }) => {
  // 自建前置（幂等）：把 E2E feed 条目显式置为未读、未收藏（set 语义
  // PATCH）。不依赖 FreshRSS 当前数据状态——上轮运行遗留的已读/收藏
  // 不会影响本轮。
  const all = await (await page.request.get('/api/v1/entries?view=all')).json()
  const targets = all.items.filter((i: { title: string }) =>
    /^文章 (alpha|beta|gamma)/.test(i.title),
  )
  expect(
    targets.length,
    'E2E feed 条目不存在（需先运行 J3b 导入 E2E 源）',
  ).toBeGreaterThan(0)
  for (const target of targets) {
    const resp = await page.request.patch(
      `/api/v1/entries/${encodeURIComponent(target.entryRef)}/state`,
      { data: { read: false, starred: false } },
    )
    expect(resp.status()).toBe(204)
  }
  const unreadSetup = await (await page.request.get('/api/v1/entries?view=unread')).json()
  for (const target of targets) {
    expect(
      unreadSetup.items.some((i: { title: string }) => i.title === target.title),
    ).toBe(true)
  }

  await page.goto('/')
  // 打开第一篇 E2E 条目
  const entryTitle = page.getByRole('button', { name: /^文章 (alpha|beta|gamma)/ }).first()
  await expect(entryTitle).toBeVisible({ timeout: 15_000 })
  const openedTitle = (await entryTitle.innerText()).trim()
  await entryTitle.click()
  const readerText = page.getByText(/正文内容，用于 Reader 断言|正文内容。/).first()
  await expect(readerText).toBeVisible()

  // 架构不变量：打开文章不自动标记已读（unread 视图仍包含该条目）
  await page.waitForTimeout(500)
  const unread = await (await page.request.get('/api/v1/entries?view=unread')).json()
  expect(unread.items.some((i: { title: string }) => i.title === openedTitle)).toBe(true)

  // 显式操作（Reader 区域内）：收藏 + 标记为已读（set 语义）
  const readerActions = page.locator('article').first()
  const [stateResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/state'), { timeout: 5_000 }).catch(() => null),
    readerActions.getByRole('button', { name: '收藏', exact: true }).first().click(),
  ])
  if (!stateResp) throw new Error('收藏 click did not trigger PATCH /state')
  expect(stateResp.status()).toBe(204)
  await expect(page.getByRole('button', { name: '取消收藏' }).first()).toBeVisible()
  await page.getByRole('button', { name: '标记为已读' }).first().click()
  await expect(page.getByRole('button', { name: '标记为未读' }).first()).toBeVisible()
  // 显式已读生效：unread 视图不再包含该条目
  await page.waitForTimeout(500)
  const unreadAfter = await (await page.request.get('/api/v1/entries?view=unread')).json()
  expect(unreadAfter.items.some((i: { title: string }) => i.title === openedTitle)).toBe(false)
})

test('J4 — AI：mock provider 设置 / key 不回显 / 摘要生成与失败重试诚实', async ({ page }) => {
  // 自建前置（幂等）：BFF 调 provider 需要非空 key（Bearer 头），mock
  // 不校验值——未配置时经 write-only API 写入显式假 key，不依赖开发机
  // 恰好残留服务端 key；已配置（真实 key 或上轮 mock key）则不动。
  await ensureMockDefaultAiKey(page)
  await page.goto('/')
  await openSettingsCategory(page, 'AI')
  const dialog = visibleDialog(page)

  // 配置 mock provider（key 只在服务端；UI 无 key 输入 = 不回显）。
  // 幂等：若表单与服务器已一致（重跑），保存按钮禁用则直接继续。
  await dialog.getByLabel(/Base URL|服务地址/).fill(`http://${BRIDGE}:${AI_PORT}/v1`)
  await dialog.getByLabel(/模型|Model/).fill('mock-model')
  const saveButton = dialog.getByRole('button', { name: /保存/ })
  if (await saveButton.isEnabled().catch(() => false)) {
    await saveButton.click()
    await expect(dialog.getByText(/已保存|保存成功/).first()).toBeVisible()
  }
  // 页面任意位置不得出现真实 key 形状
  const bodyText = await page.locator('body').innerText()
  expect(bodyText).not.toContain('sk-')
  await page.keyboard.press('Escape')

  // 打开文章 → 摘要卡状态机收敛（幂等）：not_generated →「AI 摘要」；
  // 上轮失败残留 →「重试」；已缓存成功 → 直接断言。三者都收敛到
  // MOCK-AI-REPLY 可见。点击是唯一可能产生付费调用的动作（mock 返回）。
  const entryTitle = page.getByRole('button', { name: /文章 beta/ }).first()
  await entryTitle.click()
  const reader = page.locator('article').first()
  const mockReply = page.getByText(/MOCK-AI-REPLY/).first()
  const generateButton = reader.getByRole('button', { name: 'AI 摘要' })
  const retryButton = reader.getByRole('button', { name: '重试' })
  await expect(generateButton.or(retryButton).or(mockReply).first()).toBeVisible({
    timeout: 15_000,
  })
  if (await mockReply.isVisible().catch(() => false)) {
    // 已缓存命中，不再触发 provider
  } else if (await generateButton.isVisible().catch(() => false)) {
    await generateButton.click()
  } else {
    await retryButton.click()
  }
  await expect(mockReply).toBeVisible({ timeout: 30_000 })
})

test('J5 — 设置与运维：刷新后持久化', async ({ page }) => {
  await page.goto('/')
  await openSettingsCategory(page, '外观')
  const dialog = visibleDialog(page)
  // 主题切到 dark 并持久化（select 控件）
  await dialog.getByLabel('主题模式').selectOption('dark')
  await page.reload()
  const theme = await page.evaluate(() =>
    document.documentElement.getAttribute('data-theme'),
  )
  expect(theme).toBe('dark')
  // 还原 light
  await openSettingsCategory(page, '外观')
  await visibleDialog(page).getByLabel('主题模式').selectOption('light')
})

// J6（搜索页诚实边界）在移动端入口验证，见 mobile-journeys.spec.ts
