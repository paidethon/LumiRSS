/** P13 快捷键分配 UI 回归：
 *
 * - IME 守卫：shouldIgnoreKeyEvent 纯函数 + 全局处理器 / 命令面板在
 *   组合输入期间不派发；
 * - 设置中心「快捷键」页：全量动作清单、捕获（修改）、冲突显式覆盖、
 *   保留组合拒绝、清除 / 恢复默认、导出/导入（逐条校验 + 汇总）；
 * - 帮助弹窗与设置页同源（effectiveShortcuts）反映最新绑定。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CommandPalette from '../components/CommandPalette'
import ShortcutsHelpDialog from '../components/ShortcutsHelpDialog'
import { ShortcutsSettingsSection } from '../components/settings/ShortcutsSettingsSection'
import {
  COMMAND_PALETTE_TOGGLE_EVENT,
  SHORTCUT_ACTIONS,
  effectiveShortcuts,
  shouldIgnoreKeyEvent,
  useKeyboardShortcuts,
} from '../lib/keyboard-shortcuts'
import { useReaderUi } from '../store/reader-ui'

const STORAGE_KEY = 'lumi.customShortcuts'

/** jsdom 对 isComposing / keyCode 的 init 支持不完整时的兜底：实例属性强制。 */
function makeKeyEvent(init: {
  key: string
  keyCode?: number
  ctrlKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
  isComposing?: boolean
  bubbles?: boolean
}): KeyboardEvent {
  const { isComposing, bubbles, ...rest } = init
  const event = new KeyboardEvent('keydown', {
    bubbles: bubbles ?? true,
    cancelable: true,
    ...(rest as KeyboardEventInit),
  })
  if (isComposing !== undefined && event.isComposing !== isComposing) {
    Object.defineProperty(event, 'isComposing', { value: isComposing })
  }
  if (init.keyCode !== undefined && event.keyCode !== init.keyCode) {
    Object.defineProperty(event, 'keyCode', { value: init.keyCode })
  }
  return event
}

/** 设置页捕获流程：点「修改」→ 在 window 上派发组合键。 */
function captureCombo(action: string, event: KeyboardEvent) {
  fireEvent.click(screen.getByRole('button', { name: `修改快捷键：${action}` }))
  fireEvent(window, event)
}

function renderSection() {
  return render(<ShortcutsSettingsSection />)
}

beforeEach(() => {
  window.localStorage.clear()
  useReaderUi.setState({
    section: 'home',
    scope: { kind: 'all' },
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
})

describe('P13: shouldIgnoreKeyEvent（IME 守卫纯函数）', () => {
  it('isComposing=true / keyCode=229 → 忽略；普通事件 → 不忽略', () => {
    expect(shouldIgnoreKeyEvent({ isComposing: true })).toBe(true)
    expect(shouldIgnoreKeyEvent({ isComposing: false, keyCode: 229 })).toBe(true)
    expect(shouldIgnoreKeyEvent({ keyCode: 229 })).toBe(true)
    expect(shouldIgnoreKeyEvent({ isComposing: false, keyCode: 74 })).toBe(false)
    expect(shouldIgnoreKeyEvent({})).toBe(false)
  })
})

describe('P13: 全局处理器在 IME 组合期间不派发', () => {
  function Host() {
    useKeyboardShortcuts()
    return null
  }

  function renderHost() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    return render(
      <QueryClientProvider client={queryClient}>
        <Host />
      </QueryClientProvider>,
    )
  }

  it('isComposing=true 的 u 不切换未读视图；正常 u 切换', () => {
    renderHost()
    fireEvent(window, makeKeyEvent({ key: 'u', isComposing: true }))
    expect(useReaderUi.getState().view).toBe('all')
    fireEvent(window, makeKeyEvent({ key: 'u' }))
    expect(useReaderUi.getState().view).toBe('unread')
  })

  it('keyCode=229 的 u 不切换未读视图（模拟组合期旧式码）', () => {
    renderHost()
    const composing = makeKeyEvent({ key: 'u', keyCode: 229 })
    // 模拟真实性自检：事件确实携带 229
    expect(composing.keyCode).toBe(229)
    fireEvent(window, composing)
    expect(useReaderUi.getState().view).toBe('all')
  })
})

describe('P13: 命令面板在 IME 组合期间不驱动', () => {
  function openPalette() {
    fireEvent(window, new CustomEvent(COMMAND_PALETTE_TOGGLE_EVENT))
  }

  it('Enter / Escape 组合中不上屏命令、不关闭面板', () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <CommandPalette />
      </QueryClientProvider>,
    )
    openPalette()
    const input = screen.getByLabelText('搜索命令')
    fireEvent.change(input, { target: { value: '订阅' } })
    // 唯一匹配「打开订阅管理」；组合中的 Enter 不执行
    fireEvent(input, makeKeyEvent({ key: 'Enter', isComposing: true }))
    expect(useReaderUi.getState().section).toBe('home')
    expect(screen.queryByTestId('command-palette')).not.toBeNull()
    // 组合中的 Escape 不关闭面板
    fireEvent(input, makeKeyEvent({ key: 'Escape', isComposing: true }))
    expect(screen.queryByTestId('command-palette')).not.toBeNull()
    // 非组合 Enter 照常执行（既有行为不回归）
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(useReaderUi.getState().section).toBe('subscriptions')
  })
})

describe('P13: 设置中心快捷键页（捕获 / 冲突 / 导入导出）', () => {
  it('(a) 全量 8 个动作 + 默认绑定（与 SHORTCUT_ACTIONS 同一真源）', () => {
    renderSection()
    const defaults = effectiveShortcuts()
    expect(SHORTCUT_ACTIONS).toHaveLength(8)
    for (const def of SHORTCUT_ACTIONS) {
      expect(screen.getByText(def.action)).toBeInTheDocument()
      const expected = defaults.find((d) => d.id === def.id)?.keys
      expect(screen.getByTestId(`shortcut-keys-${def.id}`)).toHaveTextContent(
        expected ?? '',
      )
      // 默认态无「已自定义」徽标、清除不可用
      expect(screen.queryAllByText('已自定义')).toHaveLength(0)
      expect(
        screen.getByRole('button', { name: `清除自定义，恢复默认：${def.action}` }),
      ).toBeDisabled()
    }
  })

  it('(b) 捕获 shift+d → 绑定更新并持久化；帮助弹窗反映新绑定', () => {
    renderSection()
    captureCombo('切换未读视图', makeKeyEvent({ key: 'd', shiftKey: true }))
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('Shift+D')
    expect(screen.getByText('已自定义')).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({
      toggleUnread: 'shift+d',
    })

    // 帮助弹窗同一真源：展示生效绑定（设置页 kbd 之外多出一份）
    render(<ShortcutsHelpDialog open onClose={vi.fn()} />)
    expect(screen.getAllByText('Shift+D').length).toBeGreaterThanOrEqual(2)
  })

  it('(b2) 捕获期间 Esc 取消（绑定不变）', () => {
    renderSection()
    fireEvent.click(screen.getByRole('button', { name: '修改快捷键：下一篇' }))
    fireEvent(window, makeKeyEvent({ key: 'Escape' }))
    expect(screen.getByTestId('shortcut-keys-next')).toHaveTextContent('j / ↓')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('(c) 冲突 → 显式「覆盖」重分配，旧动作回退默认；取消则不变', () => {
    renderSection()
    captureCombo('切换未读视图', makeKeyEvent({ key: 'x' }))
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('X')

    // 捕获同一组合给收藏 → 冲突提示（role=alert），取消不变
    fireEvent.click(screen.getByRole('button', { name: '修改快捷键：收藏 / 取消收藏当前文章' }))
    fireEvent(window, makeKeyEvent({ key: 'x' }))
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent(/已被\s*「切换未读视图」使用/)
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.getByTestId('shortcut-keys-toggleStar')).toHaveTextContent('s')
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('X')

    // 再次捕获 → 覆盖：收藏得 X，切换未读回退默认 u
    fireEvent.click(screen.getByRole('button', { name: '修改快捷键：收藏 / 取消收藏当前文章' }))
    fireEvent(window, makeKeyEvent({ key: 'x' }))
    fireEvent.click(screen.getByRole('button', { name: '覆盖' }))
    expect(screen.getByTestId('shortcut-keys-toggleStar')).toHaveTextContent('X')
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('u')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({
      toggleStar: 'x',
    })
  })

  it('(d) 保留组合（Ctrl+T）被拒绝并提示', () => {
    renderSection()
    captureCombo('切换未读视图', makeKeyEvent({ key: 't', ctrlKey: true }))
    expect(screen.getByRole('status')).toHaveTextContent('浏览器保留组合，无法分配')
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('u')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('(e) 捕获期 Backspace 清除 + 清除按钮 + 全局恢复默认', () => {
    renderSection()
    // 捕获期 Backspace：清除自定义回退默认
    captureCombo('切换未读视图', makeKeyEvent({ key: 'd', shiftKey: true }))
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('Shift+D')
    fireEvent.click(screen.getByRole('button', { name: '修改快捷键：收藏 / 取消收藏当前文章' }))
    fireEvent(window, makeKeyEvent({ key: 'Backspace' }))
    expect(screen.getByTestId('shortcut-keys-toggleStar')).toHaveTextContent('s')

    // 清除按钮：单项回退默认
    fireEvent.click(
      screen.getByRole('button', { name: '清除自定义，恢复默认：切换未读视图' }),
    )
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('u')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({})

    // 重新自定义后全局恢复默认
    captureCombo('跳转搜索', makeKeyEvent({ key: 'm', altKey: true }))
    expect(screen.getByTestId('shortcut-keys-search')).toHaveTextContent('Alt+M')
    fireEvent.click(screen.getByRole('button', { name: '恢复默认' }))
    expect(screen.getByTestId('shortcut-keys-search')).toHaveTextContent('/')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({})
  })

  it('(f) 导出 JSON 含自定义绑定；导入逐条校验（1 应用 2 跳过）', async () => {
    renderSection()
    captureCombo('切换未读视图', makeKeyEvent({ key: 'd', shiftKey: true }))

    // 导出：blob 内容为 { version, shortcuts }（lumirss-shortcuts.json）
    const originalCreate = URL.createObjectURL
    const originalRevoke = URL.revokeObjectURL
    let downloaded: Blob | null = null
    URL.createObjectURL = ((blob: Blob) => {
      downloaded = blob
      return 'blob:p13-test'
    }) as typeof URL.createObjectURL
    URL.revokeObjectURL = (() => {}) as typeof URL.revokeObjectURL
    try {
      fireEvent.click(screen.getByRole('button', { name: '导出' }))
    } finally {
      URL.createObjectURL = originalCreate
      URL.revokeObjectURL = originalRevoke
    }
    expect(downloaded).not.toBeNull()
    const exported = JSON.parse(await (downloaded as unknown as Blob).text())
    expect(exported).toEqual({
      version: 1,
      shortcuts: { toggleUnread: 'shift+d' },
    })

    // 导入：1 条有效 + 1 条未知动作 + 1 条保留组合
    const file = new File(
      [JSON.stringify({ version: 1, shortcuts: { toggleStar: 'x', bogusAction: 'z', next: 'mod+t' } })],
      'lumirss-shortcuts.json',
      { type: 'application/json' },
    )
    const input = screen.getByLabelText('导入快捷键 JSON 文件')
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('已应用 1 项，跳过 2 项'),
    )
    expect(screen.getByRole('status')).toHaveTextContent('未知动作 bogusAction')
    expect(screen.getByRole('status')).toHaveTextContent('保留组合 next')
    expect(screen.getByTestId('shortcut-keys-toggleStar')).toHaveTextContent('X')
    // 已有自定义不受影响（合并而非清空）
    expect(screen.getByTestId('shortcut-keys-toggleUnread')).toHaveTextContent('Shift+D')
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')).toEqual({
      toggleUnread: 'shift+d',
      toggleStar: 'x',
    })

    // 非 JSON 文件 → 明确失败提示
    const bad = new File(['not json {'], 'broken.json', { type: 'application/json' })
    fireEvent.change(input, { target: { files: [bad] } })
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('不是有效的 JSON 文件'),
    )
  })
})
