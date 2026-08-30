/** Gate B 测试 — 快捷键 + 分类页真实/planned 语义（AC5–AC10）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'
import { SHORTCUTS, useKeyboardShortcuts } from '../lib/keyboard-shortcuts'

/** 挂载快捷键 hook 的宿主组件（模拟 App 行为） */
function ShortcutHost() {
  useKeyboardShortcuts()
  return null
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // 预置缓存：2 条文章（供 j/k 导航与 s 收藏取数）
  queryClient.setQueryData(['feeds'], [
    { title: '源A', feedUrl: 'https://a.example/feed', category: null },
  ])
  queryClient.setQueryData(['entries', { view: 'all', scope: 'all' }], {
    pages: [
      {
        items: [
          { entryRef: 'e1.a', title: 'A', starred: false },
          { entryRef: 'e1.b', title: 'B', starred: true },
        ],
      },
    ],
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

describe('快捷键速查表页（AC7）', () => {
  it('渲染全部基础快捷键（与 SHORTCUTS 同源）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /快捷键/ }))
    await waitFor(() => {
      for (const s of SHORTCUTS) {
        expect(screen.getByText(s.action)).toBeInTheDocument()
      }
    })
  })
})

describe('快捷键行为（j/k/u/s）', () => {
  function resetState() {
    useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
    localStorage.clear()
  }

  it('j：无选中 → 选中第一篇', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })

  it('j 再按：选中第二篇；k 回到第一篇', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
    fireEvent.keyDown(window, { key: 'k' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
  })

  it('u：all ↔ unread 切换', () => {
    resetState()
    render(renderWithProviders(<ShortcutHost />))
    fireEvent.keyDown(window, { key: 'u' })
    expect(useReaderUi.getState().view).toBe('unread')
    fireEvent.keyDown(window, { key: 'u' })
    expect(useReaderUi.getState().view).toBe('all')
  })

  it('s：选中文章发起收藏 mutation（PATCH starred）', async () => {
    resetState()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(renderWithProviders(<ShortcutHost />))
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    fireEvent.keyDown(window, { key: 's' })
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(JSON.parse(String(init.body))).toEqual({ starred: true })
    })
    vi.unstubAllGlobals()
  })

  it('输入框聚焦时不劫持（硬边界 10）', () => {
    resetState()
    render(
      renderWithProviders(
        <>
          <ShortcutHost />
          <input aria-label="测试输入" data-testid="input" />
        </>,
      ),
    )
    const input = screen.getByTestId('input')
    input.focus()
    // 在 input 上按 j（事件 target=input，冒泡到 window 的监听器）
    fireEvent.keyDown(input, { key: 'j' })
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })
})

describe('分类页 planned 语义（AC10）', () => {
  it('订阅与来源页：3 个 planned action（禁用 + 归属标注）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /订阅与来源/ }))
    await waitFor(() => {
      expect(screen.getByText('添加订阅')).toBeInTheDocument()
      expect(screen.getByText('导入 / 导出 OPML')).toBeInTheDocument()
      expect(screen.getByText('RSSHub 路由', { selector: 'label' })).toBeInTheDocument()
    })
    const plannedBadges = screen.getAllByText(/planned · 001/)
    expect(plannedBadges.length).toBeGreaterThanOrEqual(3)
    // planned 按钮全部禁用
    const buttons = screen
      .getAllByRole('button')
      .filter((b) => ['添加', '导入', '打开'].includes(b.textContent ?? ''))
    expect(buttons.length).toBe(3)
    for (const b of buttons) expect(b).toBeDisabled()
  })

  it('AI 页：3 个 planned（0015/0016）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /^AI$/ }))
    await waitFor(() => {
      expect(screen.getByText('AI 总结', { selector: 'label' })).toBeInTheDocument()
      expect(screen.getByText('AI 翻译', { selector: 'label' })).toBeInTheDocument()
    })
    // planned Switch 禁用
    const switches = screen.getAllByRole('switch')
    for (const sw of switches) expect(sw).toBeDisabled()
  })

  it('数据控制页：清缓存/重置真实可用（无 planned 徽标），备份 planned', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /数据控制/ }))
    await waitFor(() => {
      expect(screen.getByText(/清除本地缓存/)).toBeInTheDocument()
      expect(screen.getByText(/恢复默认设置/)).toBeInTheDocument()
    })
    // 真实按钮可点
    expect(screen.getByRole('button', { name: '清除' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重置' })).toBeEnabled()
    // 备份 planned（0011 路线修订顺延 0017→0018）
    expect(screen.getByText(/planned · 0018/)).toBeInTheDocument()
  })

  it('重置真实生效：改设置 → 点重置 → 恢复默认', async () => {
    localStorage.clear()
    useAppSettings.getState().update({ readerFontSize: 21 })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(21)
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /数据控制/ }))
    fireEvent.click(await screen.findByRole('button', { name: '重置' }))
    expect(useAppSettings.getState().settings.readerFontSize).toBe(17)
    localStorage.clear()
  })

  it('关于页：版本/许可证/仓库/第三方链接齐全（AC9）', async () => {
    render(renderWithProviders(<SettingsModal open onClose={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /关于/ }))
    await waitFor(() => {
      expect(screen.getByText(/AGPL-3\.0-only/)).toBeInTheDocument()
      expect(screen.getByText(/paidethon\/LumiRSS/)).toBeInTheDocument()
      expect(screen.getByText(/THIRD_PARTY_NOTICES/)).toBeInTheDocument()
    })
  })
})

describe('未读圆点开关真实生效（AC5）', () => {
  it('关闭后 EntryRow 不再渲染圆点', async () => {
    const { useEntries } = await import('../api/queries')
    void useEntries
    // 直接驱动 store + 渲染 EntryRow
    const { default: EntryRow } = await import('../components/EntryRow')
    const item = {
      entryRef: 'e1.x', title: '标题', feedTitle: '源', author: null,
      url: null, publishedAt: null, read: false, starred: false,
    }
    localStorage.clear()
    // 0011 修正补充：EntryRow 内嵌 EntryActionButtons（mutation hook）
    // 需要 QueryClientProvider
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container, unmount } = render(
      <QueryClientProvider client={qc}><EntryRow item={item} selected={false} /></QueryClientProvider>,
    )
    expect(container.querySelector('span.rounded-full')).not.toBeNull()
    useAppSettings.getState().update({ timelineUnreadDot: false })
    const qc2 = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container2 = render(
      <QueryClientProvider client={qc2}><EntryRow item={item} selected={false} /></QueryClientProvider>,
    ).container
    expect(container2.querySelector('span.rounded-full')).toBeNull()
    unmount()
    useAppSettings.getState().reset()
    localStorage.clear()
  })
})
