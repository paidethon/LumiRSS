/** N070 纯键盘阅读定位 — lib + ReaderKeyNav 接线（jsdom）。
 *
 * 覆盖：类别内循环（↓/↑ 越界回绕）；Alt+Shift 切换类别（固定循环序 +
 * 会话粘滞 sessionStorage）；指示 chip 更新（链接 2/3 形态）；输入框
 * 聚焦 / IME 组合 / 模态打开时不响应；跳转不改已读状态（fetch PATCH
 * 零调用）；设置关闭时不挂监听。 */

import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderKeyNav from '../components/ReaderKeyNav'
import {
  KEYNAV_CATEGORIES,
  KEYNAV_SESSION_KEY,
  annotationTargetElements,
  collectKeyNavTargets,
  cycleIndex,
  keyNavEventAction,
  keyNavEventAllowed,
  loadKeyNavCategory,
  switchCategory,
} from '../lib/reader-keynav'
import {
  ANNOTATIONS_STORAGE_KEY,
  type Annotation,
} from '../lib/annotations'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'

const ARTICLE_HTML = [
  '<h2>标题一</h2>',
  '<p>第一段 <a href="https://a.test/1">链接一</a>。</p>',
  '<h2>标题二</h2>',
  '<p>第二段 <a href="https://a.test/2">链接二</a>。</p>',
  '<pre><code>const x = 1</code></pre>',
  '<p>第三段 <a href="https://a.test/3">链接三</a>。</p>',
].join('')

function mountReader(): { scroller: HTMLElement; article: HTMLElement } {
  const scroller = document.createElement('div')
  scroller.className = 'lumi-reader-scroll'
  scroller.innerHTML = `<div class="lumi-reader-article">${ARTICLE_HTML}</div>`
  document.body.appendChild(scroller)
  const article = scroller.querySelector('.lumi-reader-article') as HTMLElement
  return { scroller, article }
}

function pressKey(
  key: string,
  options: { alt?: boolean; shift?: boolean; target?: EventTarget } = {},
): void {
  const event = new KeyboardEvent('keydown', {
    key,
    altKey: options.alt ?? true,
    shiftKey: options.shift ?? false,
    bubbles: true,
    cancelable: true,
  })
  Object.defineProperty(event, 'target', { value: options.target ?? window })
  act(() => {
    window.dispatchEvent(event)
  })
}

function refOf(node: HTMLElement | null): React.RefObject<HTMLElement | null> {
  return { current: node }
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  vi.stubGlobal('fetch', vi.fn())
  // jsdom 无 scrollIntoView
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.querySelectorAll('.lumi-reader-scroll').forEach((el) => el.remove())
  delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe('reader-keynav 纯逻辑', () => {
  it('keyNavEventAction：Alt+↑/↓ 移动；Alt+Shift+↑/↓ 换类别；其它组合 null', () => {
    expect(keyNavEventAction({ altKey: true, key: 'ArrowDown' })).toEqual({ kind: 'move', direction: 1 })
    expect(keyNavEventAction({ altKey: true, key: 'ArrowUp' })).toEqual({ kind: 'move', direction: -1 })
    expect(keyNavEventAction({ altKey: true, shiftKey: true, key: 'ArrowDown' })).toEqual({
      kind: 'switch',
      direction: 1,
    })
    expect(keyNavEventAction({ altKey: true, shiftKey: true, key: 'ArrowUp' })).toEqual({
      kind: 'switch',
      direction: -1,
    })
    expect(keyNavEventAction({ altKey: false, key: 'ArrowDown' })).toBeNull()
    expect(keyNavEventAction({ altKey: true, key: 'j' })).toBeNull()
  })

  it('cycleIndex：循环游标（未定位 → ↓ 首个 / ↑ 末个；空类别 null）', () => {
    expect(cycleIndex(-1, 3, 1)).toBe(0)
    expect(cycleIndex(-1, 3, -1)).toBe(2)
    expect(cycleIndex(0, 3, 1)).toBe(1)
    expect(cycleIndex(2, 3, 1)).toBe(0) // 越界回绕
    expect(cycleIndex(0, 3, -1)).toBe(2)
    expect(cycleIndex(1, 0, 1)).toBeNull()
  })

  it('switchCategory / 会话粘滞：固定循环序 + sessionStorage 记忆', () => {
    expect(KEYNAV_CATEGORIES.map((c) => c.label)).toEqual(['标题', '链接', '代码块', '批注'])
    expect(switchCategory('heading', 1)).toBe('link')
    expect(switchCategory('annotation', 1)).toBe('heading') // 循环
    expect(switchCategory('heading', -1)).toBe('annotation')
    expect(loadKeyNavCategory()).toBe('heading') // 默认
    window.sessionStorage.setItem(KEYNAV_SESSION_KEY, 'code')
    expect(loadKeyNavCategory()).toBe('code')
    // 损坏值回退
    window.sessionStorage.setItem(KEYNAV_SESSION_KEY, 'weird')
    expect(loadKeyNavCategory()).toBe('heading')
  })

  it('collectKeyNavTargets：标题/链接/代码块按文档序；装饰性子树剔除', () => {
    const { article } = mountReader()
    expect(collectKeyNavTargets(article, 'heading')).toHaveLength(2)
    expect(collectKeyNavTargets(article, 'link')).toHaveLength(3)
    expect(collectKeyNavTargets(article, 'code')).toHaveLength(1)
    // 隐藏链接不算目标
    const hidden = document.createElement('a')
    hidden.href = 'https://a.test/hidden'
    hidden.setAttribute('aria-hidden', 'true')
    article.appendChild(hidden)
    expect(collectKeyNavTargets(article, 'link')).toHaveLength(3)
  })

  it('annotationTargetElements：锚点命中 → 承载元素；失效锚点诚实跳过', () => {
    const { article } = mountReader()
    const annotation: Annotation = {
      id: 'a1',
      entryRef: 'e1.a',
      color: 'yellow',
      note: '',
      anchor: { prefix: '第二段 ', exact: '链接二', suffix: '。' },
      createdAt: 1,
      contentVersion: '',
    }
    window.localStorage.setItem(ANNOTATIONS_STORAGE_KEY, JSON.stringify([annotation]))
    const targets = annotationTargetElements(article, 'e1.a')
    expect(targets).toHaveLength(1)
    expect(targets[0]!.textContent).toBe('链接二')
    // 锚点失效（正文没有该文本）→ 空表
    const lost: Annotation = {
      ...annotation,
      id: 'a2',
      anchor: { prefix: '', exact: '不存在的文本', suffix: '' },
    }
    window.localStorage.setItem(ANNOTATIONS_STORAGE_KEY, JSON.stringify([lost]))
    expect(annotationTargetElements(article, 'e1.a')).toHaveLength(0)
  })
})

describe('ReaderKeyNav 接线', () => {
  it('Alt+↓ 类别内循环跳转 + 指示 chip 更新；Alt+Shift+↓ 切换类别', () => {
    const { article, scroller } = mountReader()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerKeyNav: true },
    })
    render(<ReaderKeyNav entryRef="e1.a" enabled containerRef={refOf(scroller)} />)

    // 标题类别：↓ → 标题一（1/2）
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('标题 1/2')
    expect(document.activeElement).toBe(article.querySelectorAll('h2')[0])
    // ↓ → 标题二（2/2）；再 ↓ 回绕到标题一（1/2）
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('标题 2/2')
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('标题 1/2')

    // 切换到链接类别（跳到首个）：链接 1/3
    pressKey('ArrowDown', { shift: true })
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('链接 1/3')
    expect(document.activeElement).toBe(article.querySelectorAll('a[href]')[0])

    // 链接内 ↑↓ 循环
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('链接 2/3')
    pressKey('ArrowUp')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('链接 1/3')

    // 类别序会话粘滞：sessionStorage 已记录
    expect(window.sessionStorage.getItem(KEYNAV_SESSION_KEY)).toBe('link')
  })

  it('输入框聚焦 / IME 组合 / 模态打开时不响应；关闭开关不监听', () => {
    const { scroller } = mountReader()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerKeyNav: true },
    })
    render(<ReaderKeyNav entryRef="e1.a" enabled containerRef={refOf(scroller)} />)

    // 守卫链单测（与全局快捷键同源函数）
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    expect(keyNavEventAllowed({ target: input } as unknown as KeyboardEvent)).toBe(false)
    const modal = document.createElement('div')
    modal.setAttribute('aria-modal', 'true')
    document.body.appendChild(modal)
    expect(keyNavEventAllowed({ target: window } as unknown as KeyboardEvent)).toBe(false)
    modal.remove()
    expect(
      keyNavEventAllowed({ target: window, isComposing: true } as unknown as KeyboardEvent),
    ).toBe(false)

    // 组件级：输入框聚焦时 Alt+↓ 不跳（无 chip）
    pressKey('ArrowDown', { target: input })
    expect(screen.queryByTestId('keynav-indicator')).toBeNull()

    // 模态打开时同样不跳
    document.body.appendChild(modal)
    pressKey('ArrowDown')
    expect(screen.queryByTestId('keynav-indicator')).toBeNull()
    modal.remove()

    // 正常路径恢复
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('标题 1/2')
  })

  it('设置关闭时不监听；换文重置位置；跳转零状态写入（fetch PATCH 零调用）', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { scroller } = mountReader()
    const { rerender } = render(
      <ReaderKeyNav entryRef="e1.a" enabled={false} containerRef={refOf(scroller)} />,
    )
    pressKey('ArrowDown')
    expect(screen.queryByTestId('keynav-indicator')).toBeNull()

    // 开启并跳转
    rerender(<ReaderKeyNav entryRef="e1.a" enabled containerRef={refOf(scroller)} />)
    pressKey('ArrowDown')
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('标题 1/2')

    // 换文重置（Reader 以 key=entryRef 重挂载承载；此处同构模拟）
    rerender(<ReaderKeyNav key="keynav-e1.b" entryRef="e1.b" enabled containerRef={refOf(scroller)} />)
    expect(screen.queryByTestId('keynav-indicator')).toBeNull()

    // 全程零网络写入（跳转绝不改已读/收藏状态）
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('空类别（无批注）诚实提示「无目标」', () => {
    const { scroller } = mountReader()
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerKeyNav: true },
    })
    render(<ReaderKeyNav entryRef="e1.a" enabled containerRef={refOf(scroller)} />)
    // 切到批注类别（标题 → 链接 → 代码块 → 批注，3 次切换）
    pressKey('ArrowDown', { shift: true })
    pressKey('ArrowDown', { shift: true })
    pressKey('ArrowDown', { shift: true })
    expect(screen.getByTestId('keynav-indicator').textContent).toBe('批注（无目标）')
  })
})
