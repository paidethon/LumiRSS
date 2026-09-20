/** 快速连续选择回归（性能修复 follow-up）——修复前，连续选择不同文章
 * 会让整个 EntryList 全部行重渲染 + 每次切换重复 sanitize / refetch，
 * Reader 明显落后于选择速度。
 *
 * 本测试验证核心体验目标（不设脆弱的毫秒阈值）：
 * 1. Latest selection wins：连续选择 A→B→C→D→E 后 Reader = E；
 * 2. 慢响应晚到不得覆盖：A 的详情响应被确定性挂起，在 B 已渲染后才
 *    放行 ——「旧文晚到」由路由注入保证成立，而非靠运气；
 * 3. 选中行高亮跟随最后一次选择（aria-pressed）。
 *
 * 数据自足：E2E feed（J3b 导入 / gate8 预置）现含 6 条目，任何满足
 * 前置的栈都有 ≥5 行；不足时本测试【失败】而不是被静默跳过（跳过 =
 * 回归不可见的假绿）。
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

  // W-波次后行根内新增内容包装层：标题按钮不再是行根直接子级；
  // 用「行内带文本的 aria-pressed 按钮」定位（动作按钮均为 icon-only，
  // 无文本；与实现类名解耦）。
  const titleButtons = page
    .locator('div[data-entry-ref] button[aria-pressed]')
    .filter({ visible: true })
    .filter({ hasText: /\S/ })
  // 就绪信号 = 列表行出现（移动端没有常驻「打开设置」按钮，
  // 不能用桌面的 waitForAppReady）
  await expect(titleButtons.first()).toBeVisible({ timeout: 15_000 })
  const visibleCount = await titleButtons.count()
  expect(
    visibleCount,
    '列表数据不足：E2E 栈需已导入含 6 条目的 E2E feed（desktop-journeys J3b 或 gate8 预置）',
  ).toBeGreaterThanOrEqual(BURST)

  const titles: string[] = []
  for (let i = 0; i < BURST; i++) titles.push((await titleButtons.nth(i).textContent()) ?? '')

  const readerTitle = page.locator('article h1')
  const lastTitle = titles[BURST - 1]

  if (isDesktop) {
    // 确定性竞态注入：第一篇（A）的详情响应被挂起，其余立即放行。
    // 选择切换后释放 —— 无论应用以「取消旧请求」还是「忽略晚到写入」
    // 防护，最终都必须停在最后选择的文章上。
    let delayed = 0
    let releaseSlowA: () => void = () => {}
    const slowAGate = new Promise<void>((resolve) => {
      releaseSlowA = resolve
    })
    await page.route('**/api/v1/entries/*', async (route) => {
      if (delayed++ === 0) {
        await slowAGate
      }
      try {
        await route.continue()
      } catch {
        // 选择切换可能已 abort 该请求：与晚到场景同样安全。
      }
    })

    // 桌面：列表常驻，快速连点（不等待 Reader 完成）
    for (let i = 0; i < BURST; i++) {
      await titleButtons.nth(i).click()
    }
    // Reader 已越过 A 显示 E；此刻 A 的响应仍在挂起。
    await expect(readerTitle).toHaveText(lastTitle, { timeout: 15_000 })
    // 释放 A：晚到的旧响应不得覆盖最后选择。
    releaseSlowA()
    await page.waitForTimeout(1_500)
    await expect(readerTitle).toHaveText(lastTitle)
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

  if (isDesktop) {
    await expect(titleButtons.nth(BURST - 1)).toHaveAttribute('aria-pressed', 'true')
  }
})
