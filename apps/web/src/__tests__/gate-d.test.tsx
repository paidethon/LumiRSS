/** Gate D 测试 — 底部 Tab 导航（AC15/V7）。 */

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

describe('MobileTabBar — AC15', () => {
  it('三个 Tab：时间线 / 收藏 / 设置（nav landmark）', () => {
    renderTabBar()
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    const tabs = nav.querySelectorAll('button')
    expect(tabs).toHaveLength(3)
    expect(screen.getByRole('button', { name: /时间线/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /收藏/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /设置/ })).toBeInTheDocument()
  })

  it('点击收藏 Tab → view=starred + feed 清空', () => {
    useReaderUi.setState({ view: 'all', selectedFeedUrl: 'https://x', selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: /收藏/ }))
    expect(useReaderUi.getState().view).toBe('starred')
    expect(useReaderUi.getState().selectedFeedUrl).toBeNull()
  })

  it('点击时间线 Tab → view=all + feed 清空', () => {
    useReaderUi.setState({ view: 'starred', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: /时间线/ }))
    expect(useReaderUi.getState().view).toBe('all')
  })

  it('点击设置 Tab → 打开全屏设置页（MobileSettingsScreen）→ 关闭按钮退出', () => {
    useReaderUi.setState({ view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: '设置' }))
    // 0010a Gate E：Folo 移动端模式——分组列表首页（非 Modal）
    expect(screen.getByRole('dialog', { name: '设置' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '主设置' })).toBeInTheDocument()
    // 设置激活态（限定在底部导航内，避免与"关闭设置"按钮歧义）
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    const settingsTab = [...nav.querySelectorAll('button')].find(
      (b) => b.textContent?.includes('设置'),
    )
    expect(settingsTab).toHaveAttribute('aria-current', 'true')
    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }))
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull()
  })
  
  it('设置首页点分类行 → push 子页（返回按钮）→ 返回首页', () => {
    useReaderUi.setState({ view: 'all', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    fireEvent.click(screen.getByRole('button', { name: '设置' }))
    // 分组列表里点「外观」
    fireEvent.click(screen.getByRole('button', { name: '外观' }))
    expect(screen.getByRole('heading', { name: '外观' })).toBeInTheDocument()
    // 返回首页
    fireEvent.click(screen.getByRole('button', { name: '返回设置' }))
    expect(screen.getByRole('heading', { name: '主设置' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }))
  })

  it('Reader 打开时 Tab 栏隐藏（全屏阅读）', () => {
    useReaderUi.setState({ view: 'all', selectedFeedUrl: null, selectedEntryRef: 'e1.x' })
    renderTabBar()
    // nav 不渲染（全屏阅读时 Tab 隐藏）
    expect(screen.queryByRole('navigation', { name: '底部导航' })).toBeNull()
    // 恢复状态供后续测试
    useReaderUi.setState({ selectedEntryRef: null })
  })

  it('aria-current 反映当前 view（view=starred → 收藏激活）', () => {
    useReaderUi.setState({ view: 'starred', selectedFeedUrl: null, selectedEntryRef: null })
    renderTabBar()
    expect(screen.getByRole('button', { name: /收藏/ })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: /时间线/ })).not.toHaveAttribute('aria-current')
  })
})
