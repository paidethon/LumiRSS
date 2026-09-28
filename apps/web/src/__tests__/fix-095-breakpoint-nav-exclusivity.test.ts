/**
 * FIX-095 — 768/1024 断点附近不得同时出现两套导航/内容面板。
 *
 * 审计结论（2026-09 R2）：壳层的桌面/移动边界由「JS 档位判定 + CSS 媒体
 * 类」双层把守，未发现真实的双渲染区间。jsdom 不计算 CSS（无法断言
 * 「可见」），本文件把边界契约钉成来源级断言——任何一侧漂移（例如把
 * aside 的 `hidden lg:block` 误改成 `block`、或 MobilePageHeader 丢失
 * `lg:hidden`）都会击穿互斥，测试立即变红。
 *
 * 已核对且属设计（非双导航缺陷）的现状：
 * - 平板竖排（768–834.99）：MobilePageHeader（页面上下文 + 返回/标题）
 *   与折叠 rail（唯一常驻 nav 地标）并存——P03 平板层设计；
 *   抽屉含第二份 Sidebar，但抽屉是 modal，打开前不渲染。
 * - compact 档 DOM 中保留隐藏的 aside/rail（既有 DOM 契约），由 CSS
 *   `hidden` 卸出可达性树——不算可见双导航。
 *
 * 各档位稳态（审计记录）：
 *   <768   compact：MobileHeader + MobileTabBar（JS tier 门控 + lg:hidden
 *          双保险）；aside/rail 隐藏；移动 section（lg:hidden）替代 Timeline
 *          （max-lg:hidden）。
 *   768–1023 tablet：无底栏（tier 门控）；常驻 rail/aside；横排无顶栏。
 *   ≥1024  desktop：aside(lg:block) 或 rail(lg:flex)；MobileHeader
 *          (lg:hidden)、MobileTabBar（不渲染）、移动 section（卸载+lg:hidden）
 *          全部退场；设置壳 JS 择一渲染。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string =>
  readFileSync(resolve(__dirname, '..', rel), 'utf-8')

describe('FIX-095: 断点边界导航互斥契约', () => {
  it('App：非平板档侧栏容器 hidden lg:block / rail hidden lg:flex（≥1024 才可见）', () => {
    const app = read('App.tsx')
    // 展开态 aside：compact/desktop 分支带 hidden … lg:block
    expect(app).toMatch(
      /tier === 'tablet'\s*\?\s*'block shrink-0[^']*'\s*:\s*'hidden shrink-0[^']*lg:block'/,
    )
    // 折叠 rail：alwaysVisible 仅平板档传 true；非平板由组件内 hidden lg:flex 隐藏
    expect(app).toMatch(/alwaysVisible=\{tier === 'tablet'\}/)
  })

  it('SidebarCollapsedRail：缺省（非平板）hidden lg:flex，alwaysVisible 才常驻', () => {
    const rail = read('components/SidebarCollapsedRail.tsx')
    expect(rail).toMatch(/alwaysVisible \? 'flex' : 'hidden lg:flex'/)
  })

  it('MobilePageHeader：根 header 带 lg:hidden（≥1024 不出现第二套顶栏）', () => {
    const header = read('components/MobilePageHeader.tsx')
    expect(header).toMatch(/<header[^>]*className="[^"]*lg:hidden/)
  })

  it('MobileTabBar：App 仅 compact 档渲染 + 组件自带 lg:hidden（双保险）', () => {
    const app = read('App.tsx')
    expect(app).toMatch(/tier === 'compact' && <MobileTabBar \/>/)
    const tabbar = read('components/MobileTabBar.tsx')
    expect(tabbar).toMatch(/className="px-3 pb-2 lg:hidden"/)
  })

  it('App：移动 section lg:hidden 且桌面 Timeline 列位 max-lg:hidden（互斥）', () => {
    const app = read('App.tsx')
    // 移动 section 根：lg:hidden（且 Reader 打开时 max-lg:hidden）
    expect(app).toMatch(/overflow-y-auto bg-\[var\(--lumi-surface\)\] lg:hidden/)
    // Timeline 列：非 home section 在 <1024 隐藏（桌面列位可见性互斥）
    expect(app).toMatch(/section !== 'home' \? ' max-lg:hidden'/)
  })

  it('App：桌面独占 section（agent/graph）hidden lg:flex，仅 ≥1024 渲染本体', () => {
    const app = read('App.tsx')
    expect(app).toMatch(/hidden min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-\[var\(--lumi-surface\)\] lg:flex/)
  })

  it('SettingsShell：JS 档位择一渲染移动全屏页/桌面 Modal（portal 无法 CSS 切换）', () => {
    const shell = read('components/SettingsShell.tsx')
    expect(shell).toMatch(/isMobile \? \(\s*<MobileSettingsScreen/)
    expect(shell).toMatch(/<SettingsModal/)
    const mobile = read('lib/use-is-mobile.ts')
    expect(mobile).toMatch(/useViewportTier\(\) !== 'desktop'/)
  })
})
