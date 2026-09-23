/** settings-groups 测试 — 2026-09 批次：把已有 settings store 字段接入
 * 设置 UI（时间线组 / 阅读行为组 / 外观 / 搜索）+ R03 别名入口。
 *
 * 不重复断言 gate-e 的既有内容（「滚动时标记已读」等仅在「仍存在」
 * 层面确认，断言本体归 gate-e.test.tsx 所有）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import MobileSettingsScreen from '../components/MobileSettingsScreen'
import { useAppSettings } from '../store/app-settings'

/** mock feeds API（订阅与来源分类的 SourceAliasSettings 依赖 useFeeds） */
vi.mock('../api/queries', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/queries')>()
  return {
    ...actual,
    useFeeds: () => ({
      data: [
        { title: 'Alpha Blog', feedUrl: 'https://a.example/feed' },
        { title: 'Beta News', feedUrl: 'https://b.example/feed' },
      ],
      isPending: false,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    }),
  }
})

function withProviders(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

async function openCategory(name: string) {
  fireEvent.click(screen.getByRole('button', { name: new RegExp(name) }))
  // 等分类内容挂载（sources 分类含异步区块）
  await waitFor(() => {
    expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument()
  })
}

beforeEach(() => {
  localStorage.clear()
  useAppSettings.getState().reset()
})

describe('通用分类 · 时间线组（新接入 UI）', () => {
  it('时间线排序 select：最新/最早优先，切换写回 store', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('通用')
    const select = screen.getByRole('combobox', { name: '时间线排序' })
    expect(select).toHaveValue('newest')
    expect(screen.getByText(/列表内也可切换/)).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'oldest' } })
    expect(useAppSettings.getState().settings.timelineOrder).toBe('oldest')
  })

  it('按来源分组 toggle：默认关，切换写回 store', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('通用')
    const toggle = screen.getByRole('switch', { name: '按来源分组' })
    expect(toggle).not.toBeChecked()
    expect(screen.getByText('仅对已加载条目分组。')).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(useAppSettings.getState().settings.listGroupByFeed).toBe(true)
  })

  it('卡片滑动操作 select：四档（无/标为已读/加入稍后读/收藏），含左缘手势说明', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('通用')
    const select = screen.getByRole('combobox', { name: '卡片滑动操作' })
    // 默认值来自 BFF PortableSettings 生成物（cardSwipeAction 默认 'read'）
    expect(select).toHaveValue('read')
    expect(screen.getByText(/屏幕左缘 24px 内是返回手势/)).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'star' } })
    expect(useAppSettings.getState().settings.cardSwipeAction).toBe('star')
  })

  it('搜索组：突出匹配词开关（默认开），切换写回 store', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('通用')
    expect(screen.getByRole('heading', { name: '搜索' })).toBeInTheDocument()
    const toggle = screen.getByRole('switch', { name: '突出匹配词' })
    expect(toggle).toBeChecked()
    expect(screen.getByText('搜索结果中高亮命中片段。')).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(useAppSettings.getState().settings.searchHighlightMatches).toBe(false)
  })
})

describe('外观分类 · 侧滑返回（新接入 UI）', () => {
  it('开关默认开；关闭后写回 store（说明：仅移动端生效）', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('外观')
    const toggle = screen.getByRole('switch', { name: '侧滑返回' })
    expect(toggle).toBeChecked()
    expect(screen.getByText('仅移动端生效；关闭后仅按钮返回。')).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(useAppSettings.getState().settings.swipeBackGesture).toBe(false)
  })
})

describe('阅读分类 · 阅读行为组（新接入 UI）', () => {
  it('两个开关（阅读进度/代码换行）默认值正确，切换写回 store；N052 阅读模式默认滚动、可切分页', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('阅读')
    const progress = screen.getByRole('switch', { name: '显示阅读进度' })
    const codeWrap = screen.getByRole('switch', { name: '代码自动换行' })
    expect(progress).toBeChecked() // 默认 true
    expect(codeWrap).not.toBeChecked() // 默认 false
    fireEvent.click(codeWrap)
    // N052：「按屏翻页」开关演进为「阅读模式」select（滚动/分页）
    const mode = screen.getByRole('combobox', { name: '阅读模式' })
    expect(mode).toHaveValue('scroll')
    fireEvent.change(mode, { target: { value: 'paged' } })
    const s = useAppSettings.getState().settings
    expect(s.readerCodeWrap).toBe(true)
    expect(s.readerReadingMode).toBe('paged')
    expect(s.readerShowReadingProgress).toBe(true)
  })

  it('既有开关未被移动/删除（正文读到底自动已读 + 滚动时标记已读）', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('阅读')
    expect(screen.getByRole('switch', { name: '正文读到底自动已读' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '滚动时标记已读' })).toBeInTheDocument()
  })
})

describe('订阅与来源分类 · 来源显示别名入口（R03）', () => {
  it('别名管理区块渲染订阅列表（真实名 + 别名输入）', async () => {
    render(withProviders(<SettingsModal open onClose={() => {}} />))
    await openCategory('订阅与来源')
    expect(screen.getByRole('heading', { name: '来源显示别名' })).toBeInTheDocument()
    expect(screen.getByText('Alpha Blog')).toBeInTheDocument()
    expect(screen.getByLabelText('Alpha Blog 的别名')).toBeInTheDocument()
  })
})

describe('桌面/移动共享（新增项两端同现）', () => {
  it('移动设置子页：通用与阅读的新开关同样存在', () => {
    render(withProviders(<MobileSettingsScreen open onClose={() => {}} />))
    fireEvent.click(screen.getByRole('button', { name: '通用' }))
    expect(screen.getByRole('switch', { name: '按来源分组' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '时间线排序' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '突出匹配词' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '返回设置' }))
    fireEvent.click(screen.getByRole('button', { name: '阅读' }))
    expect(screen.getByRole('switch', { name: '显示阅读进度' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '阅读模式' })).toBeInTheDocument()
  })
})
