/** 0019 C7 — 可访问性门（axe-core）。
 *
 * 主要页面的自动扫描：0 critical / 0 serious 为硬门。
 * 页面：首页（时间线）、Reader、订阅中心、搜索、设置（外观 / 数据控制 /
 * 账户与服务）。桌面 1440 与移动 390 两个代表视口。
 */

import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import {
  closeMobileSettings,
  openMobileSettings,
  openSettingsCategory,
  visibleDialog,
} from './helpers'

async function expectNoCriticalViolations(
  page: import('@playwright/test').Page,
  includeSelector?: string,
) {
  let builder = new AxeBuilder({ page }).withTags([
    'wcag2a',
    'wcag2aa',
    'wcag21a',
    'wcag21aa',
  ])
  // 蒙层之下的页面内容不在扫描范围（不可交互且被 aria-hidden 遮挡）
  if (includeSelector) builder = builder.include(includeSelector)
  const results = await builder.analyze()
  const blocking = results.violations.filter((v) =>
    ['critical', 'serious'].includes(v.impact ?? ''),
  )
  expect(
    blocking,
    `axe violations (critical/serious): ${JSON.stringify(
      blocking.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
      null,
      2,
    )}`,
  ).toEqual([])
}

test.skip(({ viewport }) => {
  // 只在两个代表视口跑（1920/1440 桌面 + 390 移动），减少重复
  const w = viewport?.width ?? 0
  return w !== 1440 && w !== 390
}, 'representative viewports only')

test('a11y — 首页（时间线 + 侧栏/底部导航）', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '打开设置' }).or(page.getByRole('button', { name: '打开导航' })).first()).toBeVisible()
  await expectNoCriticalViolations(page)
})

test('a11y — Reader（打开文章）', async ({ page }) => {
  await page.goto('/')
  const entryTitle = page.getByRole('button', { name: /^文章 (alpha|beta|gamma)/ }).first()
  await expect(entryTitle).toBeVisible({ timeout: 15_000 })
  await entryTitle.click()
  await expect(page.getByText(/正文内容/).first()).toBeVisible()
  await expectNoCriticalViolations(page)
})

test('a11y — 设置：外观 / 数据控制 / 账户与服务', async ({ page }) => {
  await page.goto('/')
  const isMobile = (page.viewportSize()?.width ?? 0) < 1024
  const categories = ['外观', '数据控制', '账户与服务']
  if (isMobile) {
    // 移动设置只能经抽屉触达；Sheet 打开时导航抽屉仍在下层，扫描覆盖
    // 两个 dialog（同为 [role="dialog"]）。分类选择是设置屏内状态
    // （Sheet 关闭仍保留）——与 M4 一致：开一次设置，「返回设置」往返。
    const screen = await openMobileSettings(page)
    for (const category of categories) {
      await screen.getByRole('button', { name: category }).click()
      await expectNoCriticalViolations(page, '[role="dialog"]')
      await screen.getByRole('button', { name: '返回设置' }).click()
    }
    await closeMobileSettings(page)
  } else {
    for (const category of categories) {
      await openSettingsCategory(page, category)
      const dialog = visibleDialog(page)
      await expect(dialog.getByText(/./).first()).toBeVisible()
      // 蒙层之下的页面内容不在扫描范围，只扫描对话框子树
      await expectNoCriticalViolations(page, '[role="dialog"]')
      await page.keyboard.press('Escape')
    }
  }
})

test.describe('a11y — 搜索页（诚实空态，移动入口）', () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) >= 1024, 'mobile search tab')

  test('搜索页扫描', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '搜索', exact: true }).click()
    await expect(page.getByRole('searchbox').first()).toBeVisible()
    await expectNoCriticalViolations(page)
  })
})
