/** 快捷键扩展回归（pool #06）：'?' 唤起帮助弹窗、'/' 跳转搜索并聚焦
 * 输入框；帮助弹窗与设置中心共用 SHORTCUTS 单一真源。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ShortcutsHelpDialog from '../components/ShortcutsHelpDialog'
import { SHORTCUTS, useKeyboardShortcuts } from '../lib/keyboard-shortcuts'
import { useReaderUi } from '../store/reader-ui'

function Host({ onHelp }: { onHelp: () => void }) {
  useKeyboardShortcuts({ onShowShortcutsHelp: onHelp })
  return null
}

function renderHost(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

describe('「?」帮助与「/」搜索（pool #06）', () => {
  it('问号键回调唤起帮助（onShowShortcutsHelp）', () => {
    const onHelp = vi.fn()
    renderHost(<Host onHelp={onHelp} />)
    fireEvent(window, new KeyboardEvent('keydown', { key: '?', bubbles: true }))
    expect(onHelp).toHaveBeenCalledTimes(1)
  })

  it('斜杠键切到搜索 section 并聚焦搜索输入框', () => {
    renderHost(<Host onHelp={vi.fn()} />)
    const input = document.createElement('input')
    input.setAttribute('data-shortcut-target', 'search-input')
    document.body.appendChild(input)
    fireEvent(window, new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    expect(useReaderUi.getState().section).toBe('search')
    // rAF 后聚焦（与 hook 实现一致）
    return new Promise<void>((resolve) =>
      requestAnimationFrame(() => {
        expect(document.activeElement).toBe(input)
        input.remove()
        resolve()
      }),
    )
  })

  it('输入框聚焦时 / 与 ? 不劫持（isEditable 边界）', () => {
    const onHelp = vi.fn()
    renderHost(<Host onHelp={onHelp} />)
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    // 真实 keydown 从焦点元素冒泡到 window —— target 是输入框本身。
    fireEvent(input, new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    fireEvent(input, new KeyboardEvent('keydown', { key: '?', bubbles: true }))
    expect(onHelp).not.toHaveBeenCalled()
    expect(useReaderUi.getState().section).toBe('home')
    input.remove()
  })

  it('帮助弹窗渲染 SHORTCUTS 全量条目（同一真源）', () => {
    render(<ShortcutsHelpDialog open onClose={vi.fn()} />)
    for (const shortcut of SHORTCUTS) {
      expect(screen.getByText(shortcut.action)).toBeInTheDocument()
      expect(screen.getByText(shortcut.keys)).toBeInTheDocument()
    }
  })

  it('SHORTCUTS 含新增的 / 与 ? 条目', () => {
    expect(SHORTCUTS.some((s) => s.keys === '/')).toBe(true)
    expect(SHORTCUTS.some((s) => s.keys === '?')).toBe(true)
  })
})
