/** Gate 1 测试 — Shared Navigation Shell（0011 Spec AC1/AC2/AC6）。
 *
 * - 设置入口唯一位置：SidebarHeader 品牌区右上角（桌面 Modal /
 *   移动全屏页同一语义位置）；底栏与侧栏底部无设置；
 * - MobilePageHeader 三列 grid + 居中标题按 AppSection 变化；
 * - selectSection 清空 selection、保留 home 筛选。 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import MobileHeader from '../components/MobileHeader'
import MobilePageHeader from '../components/MobilePageHeader'
import MobileTabBar from '../components/MobileTabBar'
import Sidebar from '../components/Sidebar'
import { useReaderUi } from '../store/reader-ui'

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('SidebarHeader 设置入口（AC2）', () => {
  it('品牌区：LumiRSS + 流光阅源 + 右上角「打开设置」按钮', () => {
    render(withProviders(<Sidebar />))
    expect(screen.getByRole('heading', { name: 'LumiRSS' })).toBeInTheDocument()
    expect(screen.getByText('流光阅源')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '打开设置' })).toBeInTheDocument()
    // 旧底部设置行已删除（0011）
    const nav = screen.getByRole('navigation', { name: '主导航' })
    const buttons = [...nav.querySelectorAll('button')]
    expect(buttons.find((b) => b.textContent?.trim() === '设置')).toBeUndefined()
  })

  it('点「打开设置」→ 设置面板打开（同一入口承载桌面 Modal 与移动全屏页）', () => {
    render(withProviders(<Sidebar />))
    fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
    // 两种响应式壳至少其一渲染（jsdom 不算 CSS，两者都会挂载；
    // open 状态由同一 state 控制——语义上同一入口）
    const modal = screen.queryByRole('dialog', { name: '设置' })
    expect(modal).not.toBeNull()
    // 两种响应式壳同时挂载（jsdom 不算 CSS）——逐个关闭后两者都退出
    const closeButtons = screen.getAllByRole('button', { name: '关闭设置' })
    for (const btn of closeButtons) fireEvent.click(btn)
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull()
  })
})

describe('MobileTabBar 不含设置（AC1）', () => {
  it('底栏四 tab 无设置；设置仅在侧边栏品牌区', () => {
    useReaderUi.setState({ section: 'home', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    render(withProviders(<MobileTabBar />))
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    const labels = [...nav.querySelectorAll('button')].map((b) => b.textContent?.trim())
    expect(labels).toEqual(['首页', '订阅', '搜索', '收藏'])
  })
})

describe('MobilePageHeader 三列结构（AC8 语义基础）', () => {
  it('grid 三列模板 + 居中标题渲染', () => {
    render(withProviders(<MobilePageHeader title="订阅" />))
    const header = screen.getByRole('banner')
    expect(header.className).toContain('grid-cols-[44px_minmax(0,1fr)_44px]')
    expect(screen.getByRole('heading', { name: '订阅' })).toBeInTheDocument()
  })

  it('默认左侧菜单按钮（aria-controls 指向抽屉）；副标题可选', () => {
    render(withProviders(<MobilePageHeader title="全部信息流" subtitle="LumiRSS" />))
    const menu = screen.getByRole('button', { name: '打开导航' })
    expect(menu).toHaveAttribute('aria-controls', 'mobile-navigation-drawer')
    expect(screen.getByText('LumiRSS')).toBeInTheDocument()
  })

  it('自定义 left/right 插槽替代默认（无假按钮）', () => {
    render(
      withProviders(
        <MobilePageHeader
          title="阅读"
          left={<button type="button">返回文章列表</button>}
          right={<button type="button">全部</button>}
        />,
      ),
    )
    expect(screen.getByRole('button', { name: '返回文章列表' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '全部' })).toBeInTheDocument()
    // 未传默认菜单时不渲染菜单按钮
    expect(screen.queryByRole('button', { name: '打开导航' })).toBeNull()
  })
})

describe('MobileHeader 按 section 渲染标题（AC1/AC8）', () => {
  it('home：标题为动态 scope（全部信息流/未读）；Reader 打开变「阅读」+返回', () => {
    useReaderUi.setState({ section: 'home', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    const { rerender } = render(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '全部信息源' })).toBeInTheDocument()

    // 未读过滤（§23：Header 显示 Scope，过滤状态由右侧入口承载）
    useReaderUi.getState().selectView('unread')
    rerender(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '全部信息源' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '未读' })).toHaveAttribute('aria-pressed', 'true')

    // Reader 打开：标题「阅读」、左侧变返回按钮
    useReaderUi.getState().selectEntry('e1.x')
    rerender(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '阅读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回文章列表' })).toBeInTheDocument()
    useReaderUi.getState().selectEntry(null)
  })

  it('subscriptions/search/favorites：标题对应页面名', () => {
    useReaderUi.setState({ section: 'subscriptions', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    const { rerender } = render(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '订阅' })).toBeInTheDocument()

    useReaderUi.getState().selectSection('search')
    rerender(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '搜索' })).toBeInTheDocument()

    useReaderUi.getState().selectSection('favorites')
    rerender(withProviders(<MobileHeader />))
    expect(screen.getByRole('heading', { name: '收藏' })).toBeInTheDocument()
    useReaderUi.getState().selectSection('home')
  })
})

describe('selectSection 状态语义（Spec §5.1）', () => {
  it('切 section 清空 selection、保留 view/feed 筛选；重复点击无副作用', () => {
    useReaderUi.setState({ section: 'home', view: 'unread', scope: { kind: 'rss-feed', feedUrl: 'https://x' }, selectedEntryRef: 'e1' })
    useReaderUi.getState().selectSection('search')
    const s = useReaderUi.getState()
    expect(s.section).toBe('search')
    expect(s.selectedEntryRef).toBeNull()
    expect(s.view).toBe('unread')
    expect(s.scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://x' })
    // 重复点击：状态不变（幂等）
    useReaderUi.getState().selectSection('search')
    expect(useReaderUi.getState().section).toBe('search')
    useReaderUi.setState({ section: 'home', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
  })
})

describe('Sidebar 内嵌设置入口不依赖 Query 数据', () => {
  it('feeds pending 时「打开设置」仍可用（设置入口不受数据态影响）', () => {
    render(withProviders(<Sidebar />))
    const btn = screen.getByRole('button', { name: '打开设置' })
    expect(btn).toBeEnabled()
    // RSS tree 默认收起（chevron aria-expanded=false），feeds 未加载不影响品牌区
    const nav = within(screen.getByRole('navigation', { name: '主导航' }))
    expect(nav.getByRole('button', { name: '展开 RSS 分类' })).toHaveAttribute('aria-expanded', 'false')
  })
})
