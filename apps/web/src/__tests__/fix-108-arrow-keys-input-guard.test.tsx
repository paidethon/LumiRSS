/** FIX-108 — 键盘方向键：Tabs / 菜单 / 列表导航不劫持输入框内正常编辑。
 *
 * 裁决：BASELINE_OK。三处方向键消费方各有正确的作用域：
 * - Tabs（Base UI）：←/→/↑/↓ 仅在 tablist 的 roving focus 内导航——
 *   焦点在面板内的输入框时，方向键是正常光标移动，不切 tab；
 * - Menu（Base UI）：↑/↓ 仅在菜单展开期间于菜单面板内移动高亮；
 *   菜单关闭时全局没有任何方向键监听；
 * - 全局列表导航（lib/keyboard-shortcuts 的 ↓/↑ 副绑定）：挂 window，
 *   但 isEditable(target) 门控——输入框/可编辑元素聚焦时一律让位
 *   （模块头部「纪律·硬边界 10」，另有 IME/修饰键/模态门控）。
 *
 * 本组用例把三个作用域钉住，防止未来把监听挪到 document 级或去掉
 * isEditable 门控时的静默回归。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, afterEach, vi } from 'vitest'
import { Menu } from '../components/ui/Menu'
import { Tabs, type TabsOption } from '../components/ui/Tabs'
import { useKeyboardShortcuts } from '../lib/keyboard-shortcuts'
import { useReaderUi } from '../store/reader-ui'

const OPTIONS: TabsOption<'a' | 'b' | 'c'>[] = [
  { value: 'a', label: '标签甲' },
  { value: 'b', label: '标签乙' },
  { value: 'c', label: '标签丙' },
]

function TabsHarness() {
  const [value, setValue] = useState<'a' | 'b' | 'c'>('a')
  return (
    <Tabs
      aria-label="示例页签"
      value={value}
      onValueChange={setValue}
      options={OPTIONS}
      panels={{
        a: <div>面板甲</div>,
        b: (
          <div>
            <input data-testid="panel-input" placeholder="面板内输入框" />
          </div>
        ),
        c: <div>面板丙</div>,
      }}
    />
  )
}

describe('FIX-108: Tabs 方向键作用域', () => {
  it('焦点在 tab 上：→ 把焦点沿 tablist 移到下一个 tab（roving 导航生效）', async () => {
    render(<TabsHarness />)
    const tabs = screen.getAllByRole('tab')
    tabs[0]!.focus()
    // Base UI composite：keydown 移高亮 → queueMicrotask 移 DOM 焦点。
    // 注：焦点激活链（activateOnFocus → aria-selected 翻转）在 jsdom
    // 不完整（React 19 焦点委托链路无法驱动），选中态翻转那半段需浏览器
    // 验证；本环境可验证的一半——方向键把焦点约束在 tablist 内移动——
    // 由此断言钉住。
    fireEvent.keyDown(tabs[0]!, { key: 'ArrowRight' })
    await waitFor(() => expect(document.activeElement).toBe(tabs[1]))
  })

  it('焦点在面板内输入框：←/→ 不移动 tablist 焦点，焦点留在输入框（编辑不被劫持）', async () => {
    render(<TabsHarness />)
    const tabs = screen.getAllByRole('tab')
    // 点击选中第二个 tab（click 路径 jsdom 可驱动）
    fireEvent.click(tabs[1]!)
    expect(tabs[1]!).toHaveAttribute('aria-selected', 'true')

    const input = screen.getByTestId('panel-input')
    input.focus()
    fireEvent.keyDown(input, { key: 'ArrowLeft' })
    fireEvent.keyDown(input, { key: 'ArrowRight' })
    // 方向键是输入框内的光标移动：焦点不动、选中不变、tablist 无焦点移动
    expect(document.activeElement).toBe(input)
    expect(tabs[1]!).toHaveAttribute('aria-selected', 'true')
    await act(async () => {
      await Promise.resolve()
    })
    expect(tabs).not.toContain(document.activeElement)
  })
})

describe('FIX-108: Menu 方向键作用域', () => {
  it('菜单展开时 ↓ 在面板内移动高亮；关闭时全局方向键无菜单副作用', () => {
    const onSelect = vi.fn()
    function Harness() {
      return (
        <>
          <input data-testid="outside-input" placeholder="菜单外输入框" />
          <Menu
            trigger={({ triggerProps }) => (
              <button type="button" data-testid="menu-trigger" {...triggerProps}>
                菜单
              </button>
            )}
            items={[
              { key: 'one', content: '动作一' },
              { key: 'two', content: '动作二' },
            ]}
            onSelect={onSelect}
          />
        </>
      )
    }
    render(<Harness />)

    // 菜单关闭：输入框内 ↓/↑ 不产生任何菜单行为
    const input = screen.getByTestId('outside-input')
    input.focus()
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(onSelect).not.toHaveBeenCalled()

    // 展开后 ↓ 移动高亮到第二项（data-highlighted）
    fireEvent.click(screen.getByTestId('menu-trigger'))
    const menu = screen.getByRole('menu')
    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    const highlighted = menu.querySelectorAll('[data-highlighted]')
    expect(highlighted.length).toBeGreaterThan(0)
    expect(highlighted[0]!.textContent).toContain('动作二')
  })
})

describe('FIX-108: 全局列表导航（↓/↑）不劫持输入框', () => {
  function seedEntries(queryClient: QueryClient): void {
    queryClient.setQueryData(['entries', { view: 'all', scope: 'all' }], {
      pages: [
        {
          items: [
            { entryRef: 'e1.a', starred: false },
            { entryRef: 'e1.b', starred: false },
          ],
        },
      ],
      pageParams: [null],
    })
  }

  function ShortcutsHarness() {
    useKeyboardShortcuts()
    return <input data-testid="shortcuts-input" placeholder="列表外输入框" />
  }

  function mount() {
    useReaderUi.setState({
      view: 'all',
      scope: { kind: 'all' },
      section: 'home',
      selectedEntryRef: 'e1.a',
    })
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    seedEntries(queryClient)
    return render(
      <QueryClientProvider client={queryClient}>
        <ShortcutsHarness />
      </QueryClientProvider>,
    )
  }

  afterEach(() => {
    useReaderUi.setState({ selectedEntryRef: null })
  })

  it('焦点在页面（body）：↓ 选中下一篇（列表导航生效）', () => {
    mount()
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.b')
  })

  it('焦点在输入框：↓ 不切换选中（正常编辑不受全局键劫持）', () => {
    mount()
    const input = screen.getByTestId('shortcuts-input')
    input.focus()
    // 真实键盘事件派发在焦点元素上再冒泡到 window（target=输入框）；
    // jsdom 不会像浏览器那样把 window 事件重定向到 activeElement。
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(useReaderUi.getState().selectedEntryRef).toBe('e1.a')
    expect(document.activeElement).toBe(input)
  })
})
