/** w120-features — W6 收口（F120/F019/F014/F056/F057）真实 UI 入口横切面。
 *
 * 对运行中的栈（LUMIRSS_E2E_BASE_URL；session 栈经 globalSetup 预登录）
 * 验证四个新能力 journeys。全部只用可见语义 role/label——本文件同时在
 * 桌面（desktop-1920/1440）与移动（mobile-390/webkit-mobile-390 等全部
 * 项目）执行，不依赖视口专属布局；桌面专属入口按 project 分支：
 * - 命令面板：桌面 = Ctrl/Cmd+K 全局快捷键（keyboard-shortcuts 派发，
 *   仅桌面项目走此入口）；移动 = 导航抽屉内「命令面板」按钮（存在，
 *   MobileNavigationDrawer 工具区）——无需 skip。
 * - F014 阅读预算是列表工具：桌面打开文章后列表列会隐藏（0011 §27），
 *   故 journey 从列表工具行进入面板，不先开文章（注释见测试体）。
 *
 * 不依赖真实数据形态：每条 journey 都有「成功渲染」与「诚实降级」两类
 * 断言（空态/关闭语义），对空栈与有数据栈都成立。
 */

import { expect, test, type Page } from '@playwright/test'
import { waitForAppReady } from './helpers'

function isDesktopProject(): boolean {
  return test.info().project.name.startsWith('desktop')
}

/** 可见列表行的标题按钮（rapid-selection 同款约定：移动=EntryCard、
 * 桌面=EntryRow 都落在此选择器；动作按钮 icon-only 不含文本）。 */
function titleButtons(page: Page) {
  return page
    .locator('div[data-entry-ref] button[aria-pressed]')
    .filter({ visible: true })
    .filter({ hasText: /\S/ })
}

/** 打开导航抽屉（移动项目；桌面侧栏常驻无抽屉）。 */
async function openDrawer(page: Page): Promise<void> {
  await page.getByRole('button', { name: '打开导航' }).click()
}

/** 循环 Escape 直到导航抽屉收起（与 helpers.closeMobileSettings 同因：
 * 分层模态逐层关，快速连按可能撞退出动画）。 */
async function ensureDrawerClosed(page: Page): Promise<void> {
  const nav = page.locator('button[aria-label="打开导航"]')
  for (let i = 0; i < 6; i += 1) {
    if ((await nav.getAttribute('aria-expanded')) === 'false') return
    await page.keyboard.press('Escape')
    await page.waitForTimeout(150)
  }
  await expect(nav).toHaveAttribute('aria-expanded', 'false')
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await waitForAppReady(page)
})

test.describe('F120 命令面板', () => {
  test('打开 → 输入过滤有结果 → Escape 关闭（诚实降级 = 关闭零残留）', async ({ page }) => {
    const palette = page.getByRole('dialog', { name: '命令面板' })

    // 命令面板是 lazy 分包：监听器随 chunk 就绪（并行跑/弱机时可能要
    // 数秒）。打开动作以截止时间轮询重试——toggle 语义下未就绪的按键
    // 是 no-op，不会造成开-关抖动；面板一现即停。
    const deadline = Date.now() + 20_000
    if (!isDesktopProject()) {
      // 移动：先开抽屉（命令面板按钮在抽屉工具区，未开抽屉时不可见）
      await openDrawer(page)
      await expect(page.getByRole('button', { name: '命令面板' })).toBeVisible()
    }
    while (Date.now() < deadline) {
      if (isDesktopProject()) {
        // 桌面专属入口：全局 Ctrl/Cmd+K（keyboard-shortcuts 对输入框
        // 聚焦不劫持）。移动项目走抽屉按钮分支（下方）。
        await page.keyboard.press('ControlOrMeta+k')
      } else {
        await page.getByRole('button', { name: '命令面板' }).click().catch(() => {})
      }
      if (await palette.isVisible().catch(() => false)) break
      await page.waitForTimeout(300)
    }

    // 成功断言：面板打开、输入过滤有结果（导航命令全集里必含「打开首页」）
    await expect(palette).toBeVisible()
    const input = page.getByRole('combobox', { name: '搜索命令' })
    await input.fill('打开首')
    await expect(page.getByRole('option', { name: /打开首页/ })).toBeVisible()

    // 诚实降级断言：Escape 关闭且零残留（无结果空态、关闭态零渲染同理——
    // 面板关闭即从 DOM 消失，不留遮罩/焦点陷阱）
    await input.fill('绝不存在的命令xyz')
    await expect(page.getByText('没有匹配的命令')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(palette).toHaveCount(0)

    if (!isDesktopProject()) {
      // 命令面板盖在抽屉上（分层模态）：面板关了抽屉还在，再收抽屉
      await ensureDrawerClosed(page)
    }
  })
})

test.describe('F019 Library 回收站', () => {
  test('书签页 → 打开回收站面板 → 空态或列表诚实渲染', async ({ page }) => {
    // 进入书签 section：桌面侧栏常驻；移动经抽屉内 Sidebar（同一组件）。
    if (isDesktopProject()) {
      await page.getByRole('button', { name: '书签' }).click()
    } else {
      await openDrawer(page)
      await page.getByRole('button', { name: '书签' }).click()
      await ensureDrawerClosed(page)
    }

    // F019 入口：工具行「回收站」toggle（aria-pressed 门控面板挂载）
    const trashToggle = page.getByRole('button', { name: '回收站', exact: true })
    await expect(trashToggle).toBeVisible()
    await expect(trashToggle).toHaveAttribute('aria-pressed', 'false')
    await trashToggle.click()

    // 成功断言：面板可达（section aria-label=回收站）
    const panel = page.getByRole('region', { name: '回收站' }).or(
      page.locator('section[aria-label="回收站"]'),
    ).first()
    await expect(panel).toBeVisible()
    await expect(trashToggle).toHaveAttribute('aria-pressed', 'true')

    // 诚实降级断言：空栈 → 「回收站是空的」+ 过期说明；有数据 → 条目
    // 列表（kind + 删除时间）。两者必居其一，不允许既无空态又无列表。
    await expect(
      panel.getByText('回收站是空的').or(panel.getByText(/删除于/)).first(),
    ).toBeVisible()
    await expect(
      panel.getByText(/删除的书签与剪辑会先进入回收站/).or(panel.getByText(/恢复/)).first(),
    ).toBeVisible()
  })
})

test.describe('F014 阅读预算', () => {
  test('列表工具行 → 面板（预算 5/15/30/60）→ 装填或诚实空态 → 退出清理', async ({ page }) => {
    // 前置：栈里有文章才做（fixture 空栈时诚实跳过——预算候选来自未读）。
    // 注意 journey 不先打开文章：桌面打开文章后列表列整体隐藏（0011 §27
    // hidden 列位），阅读预算入口在列表工具行——预算是列表工具，从列表进。
    await expect(titleButtons(page).first()).toBeVisible({ timeout: 15_000 })
    test.skip(
      (await titleButtons(page).count()) === 0,
      'e2e 栈时间线为空（无订阅/无文章）——阅读预算无可装填候选，诚实跳过',
    )

    // 入口：列表工具行「阅读预算」toggle（双列实例在桌面隐藏列也有——
    // role 引擎排除隐藏元素，所见即所点）
    const budgetToggle = page.getByRole('button', { name: '阅读预算', exact: true })
    await expect(budgetToggle).toBeVisible()
    await budgetToggle.click()

    // 成功断言：面板出现，预算选项 5/15/30/60（role=group 预算选择）
    const budgetGroup = page.getByRole('group', { name: '预算选择' })
    await expect(budgetGroup).toBeVisible()
    for (const minutes of ['5 分钟', '15 分钟', '30 分钟', '60 分钟']) {
      await expect(budgetGroup.getByRole('button', { name: minutes, exact: true })).toBeVisible()
    }

    // 装填：点 15 分钟 → 有未读时出「共 N 篇」状态；无未读（全已读栈）
    // 时出诚实空态「当前筛选下没有可装填的未读文章」——两者必居其一。
    await budgetGroup.getByRole('button', { name: '15 分钟', exact: true }).click()
    await expect(
      page.getByText(/共 \d+ 篇/).or(page.getByText('当前筛选下没有可装填的未读文章')).first(),
    ).toBeVisible()

    // 退出清理：关闭面板（会话内临时清单，不持久化——面板卸载即清）
    await page.getByRole('button', { name: '关闭阅读预算' }).click()
    await expect(budgetGroup).toHaveCount(0)
  })
})

test.describe('F056/F057 继续阅读 + 最近打开', () => {
  test('入口可达：桌面侧栏区块 / 移动「最近阅读」覆盖层（空态诚实）', async ({ page }) => {
    if (isDesktopProject()) {
      // ---- 桌面 ----
      // F057「最近打开」是 device-local 历史：空 = 区块整体不渲染（诚实）。
      // 种子一条本机历史（addInitScript，先于应用脚本），区块必然可达。
      const seeded = [
        { entryRef: 'e2e.recent.1', feedTitle: 'e2e 种子源', title: '最近打开种子文', openedAt: new Date().toISOString() },
      ]
      await page.addInitScript(
        ([value]) => {
          localStorage.setItem('lumirss-recent-reads', value as string)
        },
        [JSON.stringify(seeded)] as const,
      )
      // F056「继续阅读」是服务端状态：经真实 API 播种一条进行中阅读。
      const entries = await (await page.request.get('/api/v1/entries?limit=5')).json()
      const entryRef = (entries.items ?? [])[0]?.entryRef as string | undefined
      if (entryRef !== undefined) {
        const put = await page.request.put('/api/v1/reading-progress', {
          data: { entryRef, paraId: 'p-1', pct: 42.5, deviceLabel: 'e2e' },
        })
        expect(put.status() === 204 || put.status() === 200).toBe(true)
      }
      await page.goto('/')
      await waitForAppReady(page)

      // F057：区块可达（种子后非空 → 必然渲染）+ 折叠开关语义
      const recent = page.locator('section[aria-label="最近打开"]')
      await expect(recent).toBeVisible()
      const toggle = recent.getByRole('button', { name: /最近打开（上限/ })
      await toggle.click()
      await expect(toggle).toHaveAttribute('aria-expanded', 'false') // 空清单收起 = 诚实
      await toggle.click()
      await expect(toggle).toHaveAttribute('aria-expanded', 'true')
      await expect(recent.getByText('最近打开种子文')).toBeVisible()

      // F056：有进行中阅读 → 卡片渲染并展示该条目（服务端空态 = 不渲染，
      // 与 F057 同语义；此处已播种所以必然可达）
      const continueReading = page.locator('[aria-label="继续阅读"]')
      await expect(continueReading).toBeVisible()
    } else {
      // ---- 移动 ----
      // 抽屉工具区「最近阅读」→ RecentReads 覆盖层（本地历史真源）。
      // 断言用文本而非 dialog accessible name（历史版本 overlay 未带
      // aria-label，文本是跨版本稳定语义）。
      await openDrawer(page)
      await page.getByRole('button', { name: '最近阅读' }).click()
      await expect(
        page.getByText('还没有阅读记录').or(page.locator('[data-testid="recent-reads-panel"] li').first()).first(),
      ).toBeVisible({ timeout: 10_000 })
      // Escape 关闭（覆盖层自带 Escape 处理；抽屉随后也在），收抽屉
      await page.keyboard.press('Escape')
      await ensureDrawerClosed(page)
    }
  })
})
