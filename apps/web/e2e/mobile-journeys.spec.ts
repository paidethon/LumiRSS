/** 0019 C5 — 移动端完整用户流程 journeys。
 *
 * 视口矩阵由 playwright.config projects（430/390/375）提供；390 为主路径。
 * 覆盖：底部导航与抽屉 / 全屏 Reader / AI 摘要 / 搜索诚实边界 /
 * 设置触达。依赖 desktop-journeys 先完成订阅（同栈串行运行）。
 */

import { expect, test, type Page } from '@playwright/test'
import {
  closeMobileSettings,
  ensureMockDefaultAiKey,
  expectNoHorizontalOverflow,
  openMobileSettings,
} from './helpers'

test.describe.configure({ mode: 'serial' })

test.skip(({ viewport }) => (viewport?.width ?? 0) >= 1024, 'mobile-only journeys')

async function openFirstEntry(page: Page) {
  const entryTitle = page.getByRole('button', { name: /^文章 (alpha|beta|gamma)/ }).first()
  await expect(entryTitle).toBeVisible({ timeout: 15_000 })
  await entryTitle.click()
}

test('M1 — 底部导航与抽屉：一级入口 / 搜索诚实 / 设置触达', async ({ page }) => {
  await page.goto('/')
  // 底部导航一级入口（时间线 / 订阅 / 搜索 / 收藏）
  for (const name of ['首页', '订阅', '搜索', '收藏']) {
    await expect(page.getByRole('button', { name, exact: true }).first()).toBeVisible()
  }
  // 底部栏不遮挡内容：页面可以滚动到底且无横向溢出
  await expectNoHorizontalOverflow(page)

  // 搜索页（0022 正式功能）：真实查询 → 诚实无结果；不假成功
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  const searchInput = page.getByRole('searchbox').first()
  await searchInput.fill('不存在的查询词')
  await searchInput.press('Enter')
  await expect(page.getByText(/没有找到与「不存在的查询词」相关的内容/)).toBeVisible()
  const bodyText = await page.locator('body').innerText()
  expect(bodyText).not.toMatch(/共 \d+ 条结果|条相关结果/)

  // 抽屉 → 设置
  const screen = await openMobileSettings(page, '数据控制')
  await expect(screen.getByText('备份概览')).toBeVisible()
  await closeMobileSettings(page)
})

test('M2 — 时间线与全屏 Reader：打开 / 全屏 / 返回 / 已读收藏', async ({ page }) => {
  await page.goto('/')
  const entryTitle = page.getByRole('button', { name: /^文章 (alpha|beta|gamma)/ }).first()
  await expect(entryTitle).toBeVisible({ timeout: 15_000 })
  await entryTitle.click()

  // 全屏 Reader：正文可见，无横向溢出
  await expect(page.getByText(/正文内容/).first()).toBeVisible()
  await expectNoHorizontalOverflow(page)

  // Reader 内显式收藏（幂等：若上次运行已收藏则先取消）。
  // Reader 是 DOM 中最靠前的浮层，取 last() 避开隐藏列表里的同名按钮。
  const unstar = page.getByRole('button', { name: '取消收藏' }).last()
  if ((await unstar.count()) > 0 && (await unstar.isVisible().catch(() => false))) {
    await unstar.click()
    await expect(page.getByRole('button', { name: '收藏', exact: true }).last()).toBeVisible()
  }
  await page.getByRole('button', { name: '收藏', exact: true }).last().click()
  await expect(page.getByRole('button', { name: '取消收藏' }).last()).toBeVisible()

  // 返回列表（列表仍在，section/view/scope 不变）
  await page.getByRole('button', { name: '返回文章列表' }).click()
  await expect(page.getByRole('button', { name: /^文章 (alpha|beta|gamma)/ }).first()).toBeVisible()
})

test('M3 — AI 摘要（mock provider）：Reader 内生成或读取缓存', async ({ page }) => {
  // 自建前置（幂等，同 J4）：provider 调用需要非空 key；mock 配置
  // （Base URL/Model）仍由 desktop-journeys 先行写入。
  await ensureMockDefaultAiKey(page)
  await page.goto('/')
  const entryTitle = page.getByRole('button', { name: /文章 beta/ }).first()
  await expect(entryTitle).toBeVisible({ timeout: 15_000 })
  await entryTitle.click()
  // 等待摘要卡进入稳定态：已缓存展示 / 未生成按钮 / 失败重试（上轮
  // 残留），三者收敛到 MOCK-AI-REPLY 可见
  const cached = page.getByText(/MOCK-AI-REPLY/).first()
  const generateButton = page.getByRole('button', { name: 'AI 摘要' }).last()
  const retryButton = page.getByRole('button', { name: '重试' }).last()
  await expect(cached.or(generateButton).or(retryButton).first()).toBeVisible({
    timeout: 15_000,
  })
  if (await cached.isVisible().catch(() => false)) {
    await expect(cached).toBeVisible()
  } else {
    await ((await generateButton.isVisible().catch(() => false))
      ? generateButton
      : retryButton
    ).click()
    await expect(page.getByText(/MOCK-AI-REPLY/).first()).toBeVisible({ timeout: 30_000 })
  }
  await page.getByRole('button', { name: '返回文章列表' }).click()
})

test('M4 — 设置触达：AI / 运维 / 备份 / WebDAV 表单可达', async ({ page }) => {
  await page.goto('/')
  // 设置屏的分类选择是屏内状态（Sheet 关闭仍保留），所以开一次设置、
  // 用「返回设置」在各分类间往返——与真人操作一致，避免重开竞态。
  const screen = await openMobileSettings(page)

  // 运维状态
  await screen.getByRole('button', { name: '账户与服务' }).click()
  await expect(screen.getByText('本地数据（lumi.sqlite）')).toBeVisible()
  await screen.getByRole('button', { name: '返回设置' }).click()

  // WebDAV 表单可达（密码写只读：input type=password 且为空）
  await screen.getByRole('button', { name: '数据控制' }).click()
  await expect(screen.getByText('WebDAV 远程备份')).toBeVisible()
  const passwordInput = screen.locator('input[type=password]').first()
  await expect(passwordInput).toHaveValue('')
  await screen.getByRole('button', { name: '返回设置' }).click()

  // AI 设置页可达（configured 状态真实展示）
  await screen.getByRole('button', { name: 'AI' }).click()
  await expect(screen.getByText(/AI 摘要|OpenAI|Provider|已配置|未配置/i).first()).toBeVisible()
  await closeMobileSettings(page)
})
