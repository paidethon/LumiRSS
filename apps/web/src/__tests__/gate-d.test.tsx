/** Gate D 测试 — 底部导航岛（0011 Gate 1 重构：四一级入口）。
 *
 * 0011 Spec AC1/AC6：
 * - 四 tab（首页/订阅/搜索/收藏），设置不在底栏（已移至 SidebarHeader）；
 * - aria-current="page" 反映 AppSection；
 * - Reader 打开时隐藏。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import MobileTabBar from '../components/MobileTabBar'
import { useReaderUi } from '../store/reader-ui'

function renderTabBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MobileTabBar />
    </QueryClientProvider>,
  )
}

describe('MobileTabBar — 0011 四入口导航岛', () => {
  it('四个 Tab：首页 / 订阅 / 搜索 / 收藏（nav landmark，无设置）', () => {
    renderTabBar()
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    const tabs = nav.querySelectorAll('button')
    expect(tabs).toHaveLength(4)
    expect(screen.getByRole('button', { name: /首页/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /订阅/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /搜索/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /收藏/ })).toBeInTheDocument()
    // 设置不在底栏（0011 硬性要求）
    expect(nav.textContent).not.toContain('设置')
  })

  it('点击订阅 → section=subscriptions（保留 home 的 view 筛选）', () => {
    useReaderUi.setState({ section: 'home', view: 'unread', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: /订阅/ }))
    expect(useReaderUi.getState().section).toBe('subscriptions')
    // section 切换不清空 home 的筛选状态（返回首页时恢复）
    expect(useReaderUi.getState().view).toBe('unread')
  })

  it('点击搜索 → section=search；再点首页 → section=home', () => {
    useReaderUi.setState({ section: 'home', view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: /搜索/ }))
    expect(useReaderUi.getState().section).toBe('search')
    fireEvent.click(screen.getByRole('button', { name: /首页/ }))
    expect(useReaderUi.getState().section).toBe('home')
  })

  it('点击收藏 → section=favorites（不再直接改 view——收藏页自持 starred 语义）', () => {
    useReaderUi.setState({ section: 'home', view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: /收藏/ }))
    expect(useReaderUi.getState().section).toBe('favorites')
  })

  it('Reader 打开时导航岛隐藏（全屏阅读）', () => {
    useReaderUi.setState({ section: 'home', view: 'all', selectedFeedUrl: null, selectedEntryRef: 'e1.x' })
    renderTabBar()
    expect(screen.queryByRole('navigation', { name: '底部导航' })).toBeNull()
    useReaderUi.setState({ selectedEntryRef: null })
  })

  it('aria-current="page" 反映当前 section', () => {
    useReaderUi.setState({ section: 'favorites', view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    expect(screen.getByRole('button', { name: /收藏/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: /首页/ })).not.toHaveAttribute('aria-current')
  })
})
