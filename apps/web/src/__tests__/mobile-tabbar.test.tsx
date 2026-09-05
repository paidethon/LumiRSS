/** 0020 AUDIT-016 — MobileTabBar 覆盖 768–1023 的 section 导航缺口。
 *
 * 768–1023px 仍是移动 section 布局（section 页面为 lg:hidden），但 Drawer 里的
 * Sidebar 只能导航到 home。底栏 section 切换器此前仅 <768（md:hidden），使
 * 「订阅 / 搜索」在平板宽度无法进入。修复把底栏延伸到整个 <1024（lg:hidden）。
 * 这里锁定该响应式类与 section 切换行为（真实断点像素由 Playwright/视觉验证）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import MobileTabBar from '../components/MobileTabBar'
import { useReaderUi } from '../store/reader-ui'

beforeEach(() => {
  useReaderUi.setState({ section: 'home', selectedEntryRef: null })
})

describe('MobileTabBar（AUDIT-016）', () => {
  it('底栏在 <1024 区间可见（lg:hidden，而非仅 <768 的 md:hidden）', () => {
    render(<MobileTabBar />)
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    expect(nav.className).toContain('lg:hidden')
    expect(nav.className).not.toContain('md:hidden')
  })

  it('点击「订阅」「搜索」切换 section（平板宽度进入这两屏的入口）', () => {
    render(<MobileTabBar />)
    fireEvent.click(screen.getByRole('button', { name: /订阅/ }))
    expect(useReaderUi.getState().section).toBe('subscriptions')
    fireEvent.click(screen.getByRole('button', { name: /搜索/ }))
    expect(useReaderUi.getState().section).toBe('search')
    fireEvent.click(screen.getByRole('button', { name: /首页/ }))
    expect(useReaderUi.getState().section).toBe('home')
  })

  it('Reader 打开时隐藏底栏（全屏阅读不受影响）', () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    render(<MobileTabBar />)
    expect(screen.queryByRole('navigation', { name: '底部导航' })).toBeNull()
  })
})
