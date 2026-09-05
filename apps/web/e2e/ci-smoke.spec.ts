/** 0019 CI 冒烟 — 在没有后端 API 的静态构建上运行（GitHub Actions）。
 *
 * 断言 shell 完整性 + 诚实降级态（API 不可用时的错误/空态 UI），
 * 不依赖任何真实上游服务。
 */

import { expect, test } from '@playwright/test'

// 专属 CI 静态构建冒烟：仅在无 API 的环境下有意义，本地全栈跑法默认跳过
test.skip(process.env.LUMIRSS_CI_STATIC !== '1', 'CI static-build only')

test('静态 shell 加载 + 打开设置', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: '打开设置' }).or(page.getByRole('button', { name: '打开导航' })).first()).toBeVisible()
})

test('数据控制在 API 降级下仍渲染诚实状态（不伪造成功）', async ({ page }) => {
  await page.goto('/')
  // 移动路径在 desktop 视口不可用 → 直接走桌面入口；反之用抽屉。
  const openBtn = page.getByRole('button', { name: '打开设置' })
  if ((await openBtn.count()) > 0) {
    await openBtn.click()
  } else {
    await page.getByRole('button', { name: '打开导航' }).click()
    await page.getByRole('button', { name: '打开设置' }).click()
  }
  const dialog = page.getByRole('dialog').filter({ visible: true }).first()
  // 「备份与恢复」已并入「数据控制」——同页承载备份能力
  await dialog.getByRole('button', { name: '数据控制' }).click()
  await expect(dialog.getByText('备份概览')).toBeVisible()
  // API 不可用 → 诚实错误态，绝不出现"已成功"的伪造状态
  await expect(dialog.getByText('已成功')).toHaveCount(0)
})
