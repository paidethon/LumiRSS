/** 快速连续选择回归（性能修复 follow-up）——修复前，连续选择不同文章
 * 会让整个 EntryList 全部行重渲染 + 每次切换重复 sanitize / refetch，
 * Reader 明显落后于选择速度。
 *
 * 本测试验证核心体验目标（不设脆弱的毫秒阈值）：
 * 1. Latest selection wins：连续选择 A→B→C→D→E 后 Reader = E；
 * 2. 无旧文章晚到覆盖：E 渲染稳定后保持不变；
 * 3. 选中行高亮跟随最后一次选择（aria-pressed）。
 *
 * 视口差异（既有交互设计）：
 * - 桌面三栏：列表常驻，可以连续快速点击 5 行；
 * - 移动端：Reader 全屏盖住列表——等价序列为「打开 → 返回 → 打开下一
 *   篇」（返回走 selectEntry(null)，Query cache 直接恢复，同样覆盖
 *   缓存命中路径）。
 *
 * 定位约定：标题按钮是行根（div[data-entry-ref]）的直接子 button 且带
 * aria-pressed（行内另有 meta 按钮与稍后读/收藏动作按钮，均不匹配该
 * 直接子选择器）。桌面 = EntryRow、移动 = EntryCard 中可见的一个。 */

import { expect, test } from '@playwright/test'

const BURST = 5

test('连续选择 5 篇文章：最后一次选择胜出且不被旧文覆盖', async ({ page }) => {
  const isDesktop = (page.viewportSize()?.width ?? 0) >= 1024
  await page.goto('/')

  const titleButtons = page
    .locator('li div[data-entry-ref] > button[aria-pressed]')
    .filter({ visible: true })
  // 就绪信号 = 列表行出现（移动端没有常驻「打开设置」按钮，
  // 不能用桌面的 waitForAppReady）
  await expect(titleButtons.first()).toBeVisible({ timeout: 15_000 })
  const visibleCount = await titleButtons.count()
  test.skip(visibleCount < BURST, '列表数据不足（需要至少 5 行）')

  const titles: string[] = []
  for (let i = 0; i < BURST; i++) titles.push((await titleButtons.nth(i).textContent()) ?? '')

  const readerTitle = page.locator('article h1')
  const lastTitle = titles[BURST - 1]

  if (isDesktop) {
    // 桌面：列表常驻，快速连点（不等待 Reader 完成）
    for (let i = 0; i < BURST; i++) {
      await titleButtons.nth(i).click()
    }
  } else {
    // 移动：打开 → 返回 → 下一篇（Reader 全屏，列表不可见）
    for (let i = 0; i < BURST; i++) {
      await titleButtons.nth(i).click()
      await expect(readerTitle).toHaveText(titles[i], { timeout: 15_000 })
      if (i < BURST - 1) {
        await page.getByRole('button', { name: '返回文章列表' }).click()
        await expect(titleButtons.first()).toBeVisible()
      }
    }
  }

  // 宽松延迟预算：最后一次选择后 Reader 最终显示 E（CI 速度不稳定，
  // 不设脆弱的硬毫秒阈值——正确性优先，性能回归由专项测量跟踪）。
  await expect(readerTitle).toHaveText(lastTitle, { timeout: 15_000 })

  // 无旧文章晚到覆盖：稳定等待后仍是最新的 E
  await page.waitForTimeout(1_500)
  await expect(readerTitle).toHaveText(lastTitle)

  if (isDesktop) {
    await expect(titleButtons.nth(BURST - 1)).toHaveAttribute('aria-pressed', 'true')
  }
})
