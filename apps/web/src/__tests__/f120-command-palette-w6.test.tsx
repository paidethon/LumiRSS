/** F120 —— 命令面板增强（Web 层）。
 *
 * - 模糊打分：子序列匹配；连续命中 > 分隔命中；前缀加分；不匹配剔除；
 * - 数据源：订阅来源 / 保存的视图命令装配与执行（scope 切换 / 事件
 *   通道）；无权限动作隐藏（privacy demo → 上下文导出命令缺席）；
 * - 关闭回焦：打开前聚焦的元素在关闭后重新获得焦点。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CommandPalette from '../components/CommandPalette'
import {
  buildCommands,
  buildContextCommands,
  filterCommandsFuzzy,
  fuzzyCommandScore,
} from '../lib/command-registry'
import { useReaderUi } from '../store/reader-ui'

const mocks = vi.hoisted(() => ({
  getSubscriptions: vi.fn(),
  getSavedSearchViews: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getSubscriptions: mocks.getSubscriptions,
    getSavedSearchViews: mocks.getSavedSearchViews,
  }
})

function renderPalette(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CommandPalette />
    </QueryClientProvider>,
  )
}

const SUBSCRIPTIONS = [
  { subscriptionRef: 'sub-1', title: 'Rust Blog', feedUrl: 'https://rust.example.com/rss' },
  { subscriptionRef: 'sub-2', title: 'AI Weekly', feedUrl: 'https://ai.example.com/rss' },
]
const SAVED_VIEWS = [
  {
    id: 'sv-1',
    name: 'AI 深度长文',
    query: 'AI 长文',
    view: 'all',
    categoryKey: 'all',
    createdAt: '2026-09-01T00:00:00Z',
    pinOrder: null,
    filters: null,
    hasFeedToken: false,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.removeItem('lumirss-privacy-demo')
  mocks.getSubscriptions.mockResolvedValue(SUBSCRIPTIONS)
  mocks.getSavedSearchViews.mockResolvedValue({ items: SAVED_VIEWS })
  useReaderUi.getState().selectSection('home')
  useReaderUi.getState().selectEntry(null)
  useReaderUi.getState().selectScope({ kind: 'all' })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('F120 模糊打分', () => {
  it('F120: 连续命中 > 分隔命中；前缀加分；断裂子序列不匹配', () => {
    const consecutive = fuzzyCommandScore('打开订阅管理', '订阅管')
    const separated = fuzzyCommandScore('打开订阅管理', '打订理')
    expect(consecutive).not.toBeNull()
    expect(separated).not.toBeNull()
    expect(consecutive).toBeGreaterThan(separated as number)
    // 前缀加分
    expect(fuzzyCommandScore('打开搜索', '打开')).toBeGreaterThan(
      fuzzyCommandScore('订阅管理', '打开') ?? -1,
    )
    // 断裂 → null
    expect(fuzzyCommandScore('打开首页', '首页x?')).toBeNull()
    // 排序：连续命中的命令排在分隔命中之前
    const commands = buildCommands(
      {
        section: 'home',
        view: 'all',
        themeMode: 'system',
        glassEffect: 'auto',
        listDensity: 'standard',
        listTimeFormat: 'relative',
      },
      {
        selectSection: () => {},
        selectView: () => {},
        updateSettings: () => {},
        goBack: () => {},
      },
    )
    const ranked = filterCommandsFuzzy(commands, '订阅管')
    expect(ranked[0]?.id).toBe('nav-subscriptions')
  })
})

describe('F120 数据源与权限门', () => {
  it('F120: 订阅来源命令执行 → 切换 rss-feed scope；保存的视图 → search + 事件通道', async () => {
    renderPalette()
    // 事件唤起面板
    window.dispatchEvent(new CustomEvent('lumirss-command-palette-toggle'))
    const input = await screen.findByRole('combobox', { name: '搜索命令' })

    // 订阅命令存在并执行
    fireEvent.change(input, { target: { value: 'Rust Blog' } })
    const rustCommand = await screen.findByRole('button', { name: /打开订阅：Rust Blog/ })
    fireEvent.click(rustCommand)
    await waitFor(() => {
      expect(useReaderUi.getState().scope).toEqual({ kind: 'rss-feed', feedUrl: 'https://rust.example.com/rss' })
      expect(useReaderUi.getState().section).toBe('home')
    })

    // 保存的视图命令执行 → 打开搜索 + 派发事件（SearchPage 监听应用）
    window.dispatchEvent(new CustomEvent('lumirss-command-palette-toggle'))
    const input2 = await screen.findByRole('combobox', { name: '搜索命令' })
    fireEvent.change(input2, { target: { value: 'AI 深度长文' } })
    let eventDetail: unknown = null
    window.addEventListener('lumirss-open-saved-view', (event) => {
      eventDetail = (event as CustomEvent).detail
    }, { once: true })
    fireEvent.click(screen.getByRole('button', { name: /保存的视图：AI 深度长文/ }))
    await waitFor(() => {
      expect(useReaderUi.getState().section).toBe('search')
      expect(eventDetail).toEqual({ query: 'AI 长文', view: 'all', categoryKey: 'all' })
    })
  })

  it('F120: 无权限动作隐藏——privacy demo 开启 → 上下文导出/朗读命令不装配', async () => {
    localStorage.setItem('lumirss-privacy-demo', '1')
    useReaderUi.getState().selectEntry('e1.abc')
    const caps = { privacyDemoOn: true, speechEnabled: true }
    const contextCommands = buildContextCommands(
      {
        section: 'home',
        view: 'all',
        themeMode: 'system',
        glassEffect: 'auto',
        listDensity: 'standard',
        listTimeFormat: 'relative',
        capabilities: caps,
      },
      { exportReader: () => {}, speakReader: () => {} },
    )
    expect(contextCommands).toEqual([]) // 负向：privacy 期间一个都不出现

    // 权限恢复 → 动作装配（需有选中文章）
    const contextCommands2 = buildContextCommands(
      {
        section: 'home',
        view: 'all',
        themeMode: 'system',
        glassEffect: 'auto',
        listDensity: 'standard',
        listTimeFormat: 'relative',
        capabilities: { privacyDemoOn: false, speechEnabled: true },
      },
      { exportReader: () => {}, speakReader: () => {} },
    )
    expect(contextCommands2.map((command) => command.id)).toEqual([
      'ctx-reader-export',
      'ctx-reader-speech',
    ])
    await Promise.resolve()
  })
})

describe('F120 关闭回焦', () => {
  it('F120: Escape 关闭后焦点回到触发元素', async () => {
    renderPalette()
    // 面板关闭时不可见；聚焦一个触发按钮后用事件唤起
    const trigger = document.createElement('button')
    trigger.textContent = '面板触发器'
    document.body.appendChild(trigger)
    trigger.focus()
    expect(document.activeElement).toBe(trigger)

    window.dispatchEvent(new CustomEvent('lumirss-command-palette-toggle'))
    await screen.findByRole('combobox', { name: '搜索命令' })
    fireEvent.keyDown(screen.getByRole('combobox', { name: '搜索命令' }), { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('combobox', { name: '搜索命令' })).toBeNull()
    })
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })
})
