/** NEW-352 外接键盘阅读模式 — 纯逻辑 + 面板（jsdom）。
 *
 * 覆盖：会话开关（sessionStorage 临时语义）；键盘检测诚实三分态；
 * 命令目录（含自定义重绑生效键位与阅读页文章域键位）；探测匹配纯函数
 * 的「不覆盖系统快捷键」纪律（修饰键 / IME 组合一律 null）；面板探测
 * 区只显示会触发的命令、绝不执行（fetch / store 零变化）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import KeyboardReadingModePanel from '../components/new351/KeyboardReadingModePanel'
import {
  KB_READING_SESSION_KEY,
  customPlainKey,
  hasPhysicalKeyboard,
  kbReadingCommands,
  matchKeyboardProbe,
  readKbReadingSession,
  writeKbReadingSession,
} from '../lib/keyboard-reading-mode'
import { useReaderUi } from '../store/reader-ui'

beforeEach(() => {
  window.sessionStorage.clear()
  useReaderUi.setState({ selectedEntryRef: null })
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('NEW-352 键盘阅读模式纯逻辑', () => {
  it('会话开关：写入/读取/清除（sessionStorage 临时语义，默认关）', () => {
    expect(readKbReadingSession()).toBe(false)
    writeKbReadingSession(true)
    expect(readKbReadingSession()).toBe(true)
    expect(window.sessionStorage.getItem(KB_READING_SESSION_KEY)).toBe('1')
    writeKbReadingSession(false)
    expect(window.sessionStorage.getItem(KB_READING_SESSION_KEY)).toBeNull()
    expect(readKbReadingSession()).toBe(false)
  })

  it('键盘检测：命中任一查询返回 true；两者皆否 false；环境不可用 null', () => {
    const mq = (query: string) => ({ matches: query === '(any-pointer: fine)' })
    expect(hasPhysicalKeyboard(mq)).toBe(true)
    const mqHover = (query: string) => ({ matches: query === '(hover: hover) and (pointer: fine)' })
    expect(hasPhysicalKeyboard(mqHover)).toBe(true)
    expect(hasPhysicalKeyboard(() => ({ matches: false }))).toBe(false)
    expect(hasPhysicalKeyboard(null)).toBeNull()
  })

  it('自定义绑定解析：无修饰键取裸键；带修饰键 → null（退出探测）', () => {
    expect(customPlainKey('shift+?')).toBe('?')
    expect(customPlainKey('j')).toBe('j')
    expect(customPlainKey('ctrl+k')).toBeNull()
    expect(customPlainKey('alt+arrowdown')).toBeNull()
  })

  it('命令目录：列表页无文章域键位；阅读页附 Alt 键位（展示 only）', () => {
    const listCatalog = kbReadingCommands({}, 'list')
    expect(listCatalog.probe.map((c) => c.id)).toEqual([
      'next', 'prev', 'toggleUnread', 'toggleStar', 'search', 'help', 'closeOverlay',
    ])
    expect(listCatalog.readerOnly).toEqual([])
    const readerCatalog = kbReadingCommands({}, 'reader')
    expect(readerCatalog.readerOnly.map((c) => c.keys)).toEqual(['Alt+↓', 'Alt+↑'])
  })

  it('命令目录：自定义重绑显示生效键位并标注（自定义）', () => {
    const catalog = kbReadingCommands({ next: 'n', toggleStar: 'ctrl+s' }, 'list')
    const next = catalog.probe.find((c) => c.id === 'next')
    expect(next?.keys).toBe('n')
    expect(next?.overridden).toBe(true)
    // ctrl+s 是修饰键组合 → 退出探测、保留展示
    const star = catalog.probe.find((c) => c.id === 'toggleStar')
    expect(star?.keys).toBe('ctrl+s')
    expect(star?.overridden).toBe(true)
  })

  it('探测匹配：裸键命中；修饰键组合与 IME 组合一律 null（系统快捷键不受影响）', () => {
    expect(matchKeyboardProbe({ key: 'j' }, {})).toBe('next')
    expect(matchKeyboardProbe({ key: 'ArrowDown' }, {})).toBe('next')
    expect(matchKeyboardProbe({ key: 'u' }, {})).toBe('toggleUnread')
    // 自定义重绑生效：旧键退出、新键命中
    expect(matchKeyboardProbe({ key: 'n' }, { next: 'n' })).toBe('next')
    expect(matchKeyboardProbe({ key: 'j' }, { next: 'n' })).toBeNull()
    // 修饰键 / IME
    expect(matchKeyboardProbe({ key: 'c', ctrlKey: true }, {})).toBeNull()
    expect(matchKeyboardProbe({ key: 'k', metaKey: true }, {})).toBeNull()
    expect(matchKeyboardProbe({ key: 'ArrowDown', altKey: true }, {})).toBeNull()
    expect(matchKeyboardProbe({ key: 'j', isComposing: true }, {})).toBeNull()
    expect(matchKeyboardProbe({ key: 'j', keyCode: 229 }, {})).toBeNull()
  })
})

describe('NEW-352 键盘阅读模式面板', () => {
  it('面板展示当前页面（列表页）命令与检测状态；启用为会话级', () => {
    render(<KeyboardReadingModePanel />)
    expect(screen.getByText(/当前页面（列表页）可执行命令/)).toBeTruthy()
    expect(screen.getByText('选中下一篇')).toBeTruthy()
    // 列表页不显示文章域键位
    expect(screen.queryByText(/纯键盘定位/)).toBeNull()
    // 启用 → sessionStorage；探测区出现
    fireEvent.click(screen.getByRole('switch'))
    expect(window.sessionStorage.getItem(KB_READING_SESSION_KEY)).toBe('1')
    expect(screen.getByRole('group', { name: '按键测试区' })).toBeTruthy()
    fireEvent.click(screen.getByRole('switch'))
    expect(window.sessionStorage.getItem(KB_READING_SESSION_KEY)).toBeNull()
  })

  it('选中文章 → 面板切换为阅读页命令（含文章域键位）', () => {
    useReaderUi.setState({ selectedEntryRef: 'rss:e1' })
    render(<KeyboardReadingModePanel />)
    expect(screen.getByText(/当前页面（阅读页）可执行命令/)).toBeTruthy()
    expect(screen.getByText(/纯键盘定位：下一个目标/)).toBeTruthy()
  })

  it('探测区按键只显示会触发的命令，绝不执行（fetch/store 零变化）', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    render(<KeyboardReadingModePanel />)
    fireEvent.click(screen.getByRole('switch'))
    const probe = screen.getByRole('group', { name: '按键测试区' })
    fireEvent.focus(probe)
    fireEvent.keyDown(probe, { key: 'j' })
    expect(screen.getByText('会触发：选中下一篇')).toBeTruthy()
    // 修饰键组合：如实显示不匹配
    fireEvent.keyDown(probe, { key: 'k', ctrlKey: true })
    expect(screen.getByText(/不匹配任何命令/)).toBeTruthy()
    // 绝不代为执行：无网络、选中文章未变（若真执行 next 会改变 store）
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(useReaderUi.getState().selectedEntryRef).toBeNull()
  })
})
