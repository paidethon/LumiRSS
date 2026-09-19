/** F30 命令面板 — registry 纯逻辑 + CommandPalette 组件行为。
 *
 * - buildCommands：导航/视图/外观/返回全集、动作复用（run 调用注入的
 *   action）、当前值「（当前）」标注、id 唯一；
 * - filterCommands：title + keywords casefold includes；空查询全量；
 * - CommandPalette：事件唤起、输入过滤、Enter 执行（store 变化断言）、
 *   上下键、Esc 关闭、Ctrl+K 全局 toggle（含输入框内关闭）、goBack 关闭
 *   浮层（registerOverlay 返回链）、无结果空态。
 */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CommandPalette from '../components/CommandPalette'
import { buildCommands, filterCommands, type CommandActions, type CommandContext } from '../lib/command-registry'
import { COMMAND_PALETTE_TOGGLE_EVENT, SHORTCUTS, useKeyboardShortcuts } from '../lib/keyboard-shortcuts'
import { goBack, initNavHistory } from '../lib/nav-history'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

const baseContext: CommandContext = {
  section: 'home',
  view: 'all',
  themeMode: 'system',
  glassEffect: 'auto',
  listDensity: 'standard',
  listTimeFormat: 'relative',
}

function makeActions(): CommandActions {
  return {
    selectSection: vi.fn(),
    selectView: vi.fn(),
    updateSettings: vi.fn(),
    goBack: vi.fn(),
  }
}

function openPalette() {
  fireEvent(window, new CustomEvent(COMMAND_PALETTE_TOGGLE_EVENT))
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
})

afterEach(() => {
  useAppSettings.getState().update({ themeMode: 'system', glassEffect: 'auto', listDensity: 'standard', listTimeFormat: 'relative' })
  useReaderUi.setState({ section: 'home', scope: { kind: 'all' }, view: 'all', selectedEntryRef: null })
  vi.restoreAllMocks()
})

describe('command-registry 纯逻辑', () => {
  it('buildCommands：导航 12 + 返回 + 视图 4 + 外观（主题3/玻璃3/密度3/时间2）；id 唯一', () => {
    const actions = makeActions()
    const commands = buildCommands({ ...baseContext, themeMode: 'dark' }, actions)
    const byId = new Map(commands.map((c) => [c.id, c]))
    // 导航命令与 AppSection 一一对应
    for (const id of ['home', 'subscriptions', 'search', 'favorites', 'bookmarks', 'workspaces', 'clips', 'snapshots', 'inbox', 'obsidian', 'agent', 'graph']) {
      expect(byId.get(`nav-${id}`)).toBeDefined()
    }
    expect(byId.get('nav-back')).toBeDefined()
    for (const view of ['all', 'unread', 'starred', 'read-later']) {
      expect(byId.get(`view-${view}`)).toBeDefined()
    }
    for (const theme of ['light', 'dark', 'system']) expect(byId.get(`theme-${theme}`)).toBeDefined()
    for (const glass of ['on', 'off', 'auto']) expect(byId.get(`glass-${glass}`)).toBeDefined()
    for (const density of ['compact', 'standard', 'comfortable']) expect(byId.get(`density-${density}`)).toBeDefined()
    for (const time of ['relative', 'absolute']) expect(byId.get(`time-${time}`)).toBeDefined()
    expect(new Set(commands.map((c) => c.id)).size).toBe(commands.length)
  })

  it('run 复用注入动作；当前值以「（当前）」标注', () => {
    const actions = makeActions()
    const commands = buildCommands({ ...baseContext, themeMode: 'dark' }, actions)
    commands.find((c) => c.id === 'nav-search')!.run()
    expect(actions.selectSection).toHaveBeenCalledWith('search')
    commands.find((c) => c.id === 'view-unread')!.run()
    expect(actions.selectView).toHaveBeenCalledWith('unread')
    commands.find((c) => c.id === 'theme-dark')!.run()
    expect(actions.updateSettings).toHaveBeenCalledWith({ themeMode: 'dark' })
    commands.find((c) => c.id === 'nav-back')!.run()
    expect(actions.goBack).toHaveBeenCalledTimes(1)
    // 当前值标注
    expect(commands.find((c) => c.id === 'theme-dark')!.title).toContain('（当前）')
    expect(commands.find((c) => c.id === 'theme-light')!.title).not.toContain('（当前）')
    expect(commands.find((c) => c.id === 'view-all')!.title).toContain('（当前）')
  })

  it('filterCommands：title/keywords casefold includes；空查询全量；无匹配空数组', () => {
    const commands = buildCommands(baseContext, makeActions())
    expect(filterCommands(commands, '')).toHaveLength(commands.length)
    expect(filterCommands(commands, '深色').map((c) => c.id)).toEqual(['theme-dark'])
    // keywords 英文别名 casefold
    expect(filterCommands(commands, 'DARK').map((c) => c.id)).toEqual(['theme-dark'])
    expect(filterCommands(commands, 'HOME').map((c) => c.id)).toEqual(['nav-home'])
    expect(filterCommands(commands, '不存在的命令词')).toEqual([])
  })

  it('SHORTCUTS 速查表包含命令面板条目', () => {
    expect(SHORTCUTS.some((s) => s.keys.includes('K') && s.action === '命令面板')).toBe(true)
  })
})

describe('CommandPalette 组件', () => {
  it('事件唤起 → 输入过滤 → 点击执行（store 变化）→ 面板关闭', async () => {
    render(<CommandPalette />)
    expect(screen.queryByTestId('command-palette')).toBeNull()
    openPalette()
    expect(screen.getByRole('dialog', { name: '命令面板' })).toBeInTheDocument()

    const input = screen.getByLabelText('搜索命令')
    fireEvent.change(input, { target: { value: '深色' } })
    const option = screen.getByRole('option', { name: /深色主题/ })
    fireEvent.click(within(option).getByRole('button'))
    expect(useAppSettings.getState().settings.themeMode).toBe('dark')
    // 执行后面板关闭
    await waitFor(() => expect(screen.queryByTestId('command-palette')).toBeNull())
  })

  it('上下键移动选中项，Enter 执行；无结果空态', () => {
    render(<CommandPalette />)
    openPalette()
    const input = screen.getByLabelText('搜索命令')
    fireEvent.change(input, { target: { value: '订阅' } })
    // 唯一匹配「打开订阅管理」；直接 Enter 执行
    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(useReaderUi.getState().section).toBe('subscriptions')

    // 无结果空态
    openPalette()
    const input2 = screen.getByLabelText('搜索命令')
    fireEvent.change(input2, { target: { value: 'zzz不存在的命令' } })
    expect(screen.getByText('没有匹配的命令')).toBeInTheDocument()
    // Enter 无选中项不执行、不崩溃
    fireEvent.keyDown(input2, { key: 'Enter' })
  })

  it('上下键在多结果间循环；Escape 关闭', () => {
    render(<CommandPalette />)
    openPalette()
    const input = screen.getByLabelText('搜索命令')
    // 外观：主题 三条命令
    fireEvent.change(input, { target: { value: '主题' } })
    const options = screen.getAllByRole('option')
    expect(options.length).toBe(3)
    expect(options[0]!.getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    const optionsAfter = screen.getAllByRole('option')
    expect(optionsAfter[1]!.getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    // 0 - 1 循环到末尾
    expect(screen.getAllByRole('option')[2]!.getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(screen.queryByTestId('command-palette')).toBeNull()
  })

  it('Ctrl/⌘+K 全局唤起/关闭（toggle）；输入框内 Ctrl+K 关闭', () => {
    // useKeyboardShortcuts 内部用 useQueryClient → 需要 Provider
    function Host() {
      useKeyboardShortcuts()
      return <CommandPalette />
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <Host />
      </QueryClientProvider>,
    )
    // 全局 Ctrl+K 打开
    fireEvent(window, new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))
    expect(screen.getByTestId('command-palette')).toBeInTheDocument()
    // ⌘（meta）同样生效于关闭（toggle）
    fireEvent(window, new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }))
    expect(screen.queryByTestId('command-palette')).toBeNull()

    // 打开后焦点在输入框：输入框内 Ctrl+K 由面板内部处理 → 关闭
    openPalette()
    const input = screen.getByLabelText('搜索命令')
    fireEvent.keyDown(input, { key: 'k', ctrlKey: true })
    expect(screen.queryByTestId('command-palette')).toBeNull()
  })

  it('普通输入框聚焦时 Ctrl+K 不触发（既有纪律保持）', () => {
    function Host() {
      useKeyboardShortcuts()
      return null
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <Host />
      </QueryClientProvider>,
    )
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireEvent(input, new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true }))
    expect(screen.queryByTestId('command-palette')).toBeNull()
    input.remove()
  })

  it('返回链：goBack() 关闭打开的面板（registerOverlay 登记）', async () => {
    window.history.replaceState(null, '', '/')
    initNavHistory()
    render(<CommandPalette />)
    openPalette()
    expect(screen.getByTestId('command-palette')).toBeInTheDocument()
    expect(goBack()).toBe(true)
    await waitFor(() => expect(screen.queryByTestId('command-palette')).toBeNull())
  })
})
