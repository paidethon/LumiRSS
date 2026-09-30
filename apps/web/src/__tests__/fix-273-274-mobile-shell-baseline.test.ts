/**
 * FIX-273 / FIX-274 — 移动底栏与导航抽屉基线守卫（source-level 断言）。
 *
 * FIX-273（底栏双击缩放）：MobileTabBar 是普通 button（type=button +
 * 单一 onClick 导航），不挂任何 touch/双击监听、不 preventDefault
 * 手势——系统的可访问性缩放（double-tap zoom）不被拦截；重复点按同
 * 一 tab 只是幂等的 selectSection，不会「打开两次详情」。
 *
 * FIX-274（抽屉关闭动画中的悬空操作）：抽屉条件挂载（mobileSidebarOpen
 * 才渲染 DrawerSheet），关闭本体由 Base UI Drawer 接管（Escape/遮罩/
 * ✕/导航回调 onClose），抽屉内没有会二次提交的表单——关闭过渡里不
 * 存在可达的提交动作。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

const tabBar = read('components/MobileTabBar.tsx')
const drawer = read('components/MobileNavigationDrawer.tsx')
const sheet = read('components/ui/Sheet.tsx')

describe('FIX-273: 底栏不拦截系统缩放、点按幂等', () => {
  it('MobileTabBar 无 touch/双击/滚轮监听（不与页面缩放抢占）', () => {
    expect(tabBar).not.toMatch(/onTouchStart|onTouchMove|onTouchEnd|onDoubleClick|onWheel/)
    expect(tabBar).not.toMatch(/addEventListener\(/)
    expect(tabBar).not.toMatch(/preventDefault\(\)/)
  })

  it('四个入口都是 type=button 的单一 onClick 导航（幂等 selectSection）', () => {
    expect(tabBar).toMatch(/key=\{tab\.key\}/)
    expect(tabBar).toMatch(/onClick=\{\(\) => selectSection\(tab\.key\)\}/)
    expect(tabBar).toMatch(/aria-current=\{active \? 'page' : undefined\}/)
  })
})

describe('FIX-274: 抽屉条件挂载、关闭语义归 Base UI', () => {
  it('mobileSidebarOpen 才渲染 DrawerSheet（关闭即卸载，无悬空可交互层）', () => {
    expect(drawer).toMatch(/\{mobileSidebarOpen && \(/)
    expect(drawer).toMatch(/open=\{mobileSidebarOpen\}/)
    expect(drawer).toMatch(/onClose=\{closeMobileSidebar\}/)
  })

  it('抽屉内无表单/提交动作；导航即关闭（onNavigate=closeMobileSidebar）', () => {
    expect(drawer).not.toMatch(/<form[\s>]/)
    expect(drawer).not.toMatch(/onSubmit=/)
    expect(drawer).toMatch(/onNavigate=\{closeMobileSidebar\}/)
  })

  it('Sheet 基于 Base UI Drawer（Escape/遮罩/focus/滚动锁由底座接管）', () => {
    expect(sheet).toMatch(/from '@base-ui\/react\/drawer'/)
  })
})
