/** Gate C 测试 — Sidebar 信息架构（AC12）+ 分栏拖拽/折叠/持久化（AC13/AC14/AC17）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import Sidebar from '../components/Sidebar'
import App from '../App'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

/** Provider 包装（Sidebar 内嵌 SettingsModal 用 useQueryClient） */
function withProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

/** mock feeds API（Sidebar 依赖 useFeeds） */
vi.mock('../api/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/queries')>()
  return {
    ...actual,
    useFeeds: () => ({
      data: [
        { title: '源A', feedUrl: 'https://a.example/feed' },
        { title: '源B', feedUrl: 'https://b.example/feed' },
      ],
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    }),
  }
})

describe('Sidebar 信息架构（AC12/V8）', () => {
  function renderSidebar() {
    render(withProviders(<Sidebar />))
  }

  it('两组结构：信息来源 + 工作区', () => {
    renderSidebar()
    expect(screen.getByRole('group', { name: '信息来源' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '工作区' })).toBeInTheDocument()
  })

  it('可用项：全部信息源+未读 / RSS 订阅（主区域=scope，chevron=tree）/ 稍后读 / 收藏 / 设置（品牌区）', () => {
    renderSidebar()
    expect(screen.getByRole('button', { name: /全部信息源/ })).toBeEnabled()
    // 0011 修正补充：未读过滤子项挂在全部信息流行
    expect(screen.getByRole('button', { name: '未读' })).toBeEnabled()
    // 0011 阻断修复：RSS 主区域 = scope（无 expanded 语义）；chevron 才是
    // tree 开关（aria-expanded，默认收起）——两个行为完全分离（§6/§7）
    expect(screen.getByRole('button', { name: /RSS 订阅/ })).toBeEnabled()
    const rssChevron = screen.getByRole('button', { name: '展开 RSS 分类' })
    expect(rssChevron).toBeEnabled()
    expect(rssChevron).toHaveAttribute('aria-expanded', 'false')
    expect(rssChevron).toHaveAttribute('aria-controls', 'sidebar-rss-tree')
    // 0011 修正补充 §11：工作区 = 稍后读（Clock）+ 收藏（原时间线入口
    // 移除，all 视图由全部信息流承载）
    expect(screen.getByRole('button', { name: '稍后读' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '收藏' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /时间线/ })).toBeNull()
    // 0011：设置入口在品牌区右上角（SidebarHeader），底部设置行已删除
    expect(screen.getByRole('button', { name: '打开设置' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '设置' })).toBeNull()
  })

  it('Phase 2 项可见但禁用（9 项 + Phase 2 徽标）', () => {
    renderSidebar()
    const planned = [
      '网页剪藏', '网页快照', 'API 来源', '邮件简报', '书签', 'Obsidian 库',
      'Agent 工作台', 'RAG 索引', '标签 / 图谱',
    ]
    for (const label of planned) {
      const el = screen.getByText(label).closest('[aria-disabled="true"]')
      expect(el).not.toBeNull()
    }
    const badges = screen.getAllByText('Phase 2')
    expect(badges.length).toBe(9)
  })

  it('Phase 2 项不可点击（无 button 语义）', () => {
    renderSidebar()
    // Agent 工作台等不是 button（div + aria-disabled）
    expect(screen.queryByRole('button', { name: /Agent 工作台/ })).toBeNull()
  })

  it('未读过滤子项点击 → view=unread + selection 清空', () => {
    useReaderUi.setState({ view: 'all', selectedEntryRef: 'x', scope: { kind: 'all' } })
    renderSidebar()
    fireEvent.click(screen.getByRole('button', { name: '未读' }))
    expect(useReaderUi.getState().view).toBe('unread')
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })
})

describe('分栏折叠/展开 + 持久化（AC13/AC17）', () => {
  function setup() {
    localStorage.clear()
    useAppSettings.getState().reset()
    render(withProviders(<App />))
  }

  it('折叠侧栏 → 展开按钮出现 → 展开恢复 + 持久化', async () => {
    setup()
    const collapseBtn = await screen.findByRole('button', { name: '折叠侧栏' })
    fireEvent.click(collapseBtn)
    // 折叠态：展开按钮出现
    expect(await screen.findByRole('button', { name: '展开侧栏' })).toBeInTheDocument()
    // 持久化
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!).sidebarCollapsed).toBe(true)
    // 展开
    fireEvent.click(screen.getByRole('button', { name: '展开侧栏' }))
    expect(await screen.findByRole('button', { name: '折叠侧栏' })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!).sidebarCollapsed).toBe(false)
    localStorage.clear()
  })

  it('隐藏/显示同一按钮切换（0011 §27）+ 持久化 + 隐藏后无窄栏', async () => {
    setup()
    // 可见时：列表头内「隐藏文章列表」
    const toggleBtn = await screen.findByRole('button', { name: '隐藏文章列表' })
    fireEvent.click(toggleBtn)
    // 隐藏后：Reader 侧顶出现「显示文章列表」（列表头 toggle 变为同义
    // aria-label 但其容器已 lg:hidden 退出桌面布局——点击任一恢复）
    expect((await screen.findAllByRole('button', { name: '显示文章列表' })).length).toBeGreaterThan(0)
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!).timelineCollapsed).toBe(true)
    // 再点 → 恢复显示 + 持久化
    fireEvent.click(screen.getAllByRole('button', { name: '显示文章列表' })[0]!)
    expect(await screen.findByRole('button', { name: '隐藏文章列表' })).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!).timelineCollapsed).toBe(false)
    localStorage.clear()
  })
})

describe('PaneSeparator 语义（AC14/V6）', () => {
  it('role=separator + aria 属性齐全（App 渲染后）', async () => {
    localStorage.clear()
    useAppSettings.getState().reset()
    render(withProviders(<App />))
    const sidebarSep = await screen.findByRole('separator', { name: '侧栏宽度' })
    expect(sidebarSep).toHaveAttribute('aria-orientation', 'vertical')
    expect(sidebarSep).toHaveAttribute('aria-valuemin', '220')
    expect(sidebarSep).toHaveAttribute('aria-valuemax', '300')
    expect(sidebarSep).toHaveAttribute('aria-valuenow', '240')
    const timelineSep = screen.getByRole('separator', { name: '文章列表宽度' })
    expect(timelineSep).toHaveAttribute('aria-valuemin', '360')
    expect(timelineSep).toHaveAttribute('aria-valuemax', '460')
    localStorage.clear()
  })

  it('键盘 ←/→ 微调宽度 ±10px + 持久化', async () => {
    localStorage.clear()
    useAppSettings.getState().reset()
    render(withProviders(<App />))
    const sep = await screen.findByRole('separator', { name: '侧栏宽度' })
    fireEvent.keyDown(sep, { key: 'ArrowRight' })
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(250)
    expect(JSON.parse(localStorage.getItem('lumirss-settings')!).sidebarWidth).toBe(250)
    fireEvent.keyDown(sep, { key: 'ArrowLeft' })
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(240)
    localStorage.clear()
  })

  it('键盘调宽 clamp 在边界内', async () => {
    localStorage.clear()
    useAppSettings.getState().reset()
    render(withProviders(<App />))
    const sep = await screen.findByRole('separator', { name: '侧栏宽度' })
    // 压到最小边界以下（240 - 10*3 = 210 → clamp 220）
    fireEvent.keyDown(sep, { key: 'ArrowLeft' })
    fireEvent.keyDown(sep, { key: 'ArrowLeft' })
    fireEvent.keyDown(sep, { key: 'ArrowLeft' })
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(220)
    localStorage.clear()
  })

  it('双击重置默认宽度', async () => {
    localStorage.clear()
    useAppSettings.getState().reset()
    useAppSettings.getState().update({ sidebarWidth: 280 })
    render(withProviders(<App />))
    const sep = await screen.findByRole('separator', { name: '侧栏宽度' })
    fireEvent.doubleClick(sep)
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(240)
    localStorage.clear()
  })
})
