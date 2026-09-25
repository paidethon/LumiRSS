/** R5 批3 测试 — F062 逐段专注 / F076 遮挡聚焦模式 / F063 连续阅读
 * 护眼提醒 / F080 当前会话阅读时长。
 *
 * 覆盖：纯逻辑（块收集/步进钳制/点击让位/键位门控）、ReadingRuler 遮挡
 * 模式渲染与持久化、ReadingBreakReminder 计时提示、会话时长格式化与
 * Aa 面板显示、全局 j/k 下一篇快捷键的截停共存。 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReaderAaPanel from '../components/ReaderAaPanel'
import ReadingBreakReminder from '../components/ReadingBreakReminder'
import { ReadingRuler, readRulerMode, READING_RULER_MODE_KEY } from '../components/ReadingRuler'
import {
  applyParaFocusIndex,
  clearParaFocus,
  getParaFocusBlocks,
  moveParaFocusIndex,
  paraFocusClickAllowed,
  paraFocusKeyAllowed,
} from '../lib/reader-para-focus'
import { formatSessionDuration } from '../lib/reader-tools'
import { DEFAULT_APP_SETTINGS, normalizeSettings, useAppSettings } from '../store/app-settings'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

function mountArticle(): { article: HTMLElement; scroller: HTMLElement } {
  const scroller = document.createElement('div')
  scroller.className = 'lumi-reader-scroll'
  const article = document.createElement('article')
  article.className = 'lumi-reader lumi-reader-article'
  const content = document.createElement('div')
  content.className = 'article-content'
  content.innerHTML = '<p id="p1">第一段</p><p id="p2">第二段</p><p id="p3">第三段</p>'
  article.appendChild(content)
  scroller.appendChild(article)
  document.body.appendChild(scroller)
  return { article, scroller }
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document
    .querySelectorAll('.lumi-reader-scroll, [data-lumi-reading-ruler]')
    .forEach((el) => el.remove())
  vi.restoreAllMocks()
})

// ---- F062：纯逻辑 ----

describe('F062 — reader-para-focus 纯逻辑', () => {
  it('块收集按文档序；apply 幂等、clear 完整还原', () => {
    const { article } = mountArticle()
    const blocks = getParaFocusBlocks(article)
    expect(blocks.map((b) => b.id)).toEqual(['p1', 'p2', 'p3'])
    applyParaFocusIndex(blocks, 1)
    expect(article.querySelector('[data-lumi-para-focus-active]')?.id).toBe('p2')
    clearParaFocus(article)
    expect(article.querySelectorAll('[data-lumi-para-focus-active]').length).toBe(0)
  })

  it('步进钳制：首段前 k 停留、末段后 j 停留、空正文恒 -1', () => {
    expect(moveParaFocusIndex(3, 0, -1)).toBe(0)
    expect(moveParaFocusIndex(3, 2, 1)).toBe(2)
    expect(moveParaFocusIndex(3, -1, 1)).toBe(0)
    expect(moveParaFocusIndex(3, -1, -1)).toBe(2)
    expect(moveParaFocusIndex(0, -1, 1)).toBe(-1)
  })

  it('点击让位：链接/按钮/批注/选区不触发段聚焦', () => {
    const { article } = mountArticle()
    expect(paraFocusClickAllowed(article.querySelector('p'))).toBe(true)
    expect(paraFocusClickAllowed(article.querySelector('p'))).toBe(true)
    // 链接让位
    const anchor = document.createElement('a')
    anchor.textContent = '链接'
    article.querySelector('p')!.appendChild(anchor)
    expect(paraFocusClickAllowed(anchor)).toBe(false)
    // 非空选区让位（正文段落上划选后点击段落不抢）
    const range = document.createRange()
    range.selectNodeContents(article.querySelector('#p2')!)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    expect(paraFocusClickAllowed(article.querySelector('#p1'))).toBe(false)
    selection?.removeAllRanges()
    expect(paraFocusClickAllowed(article.querySelector('#p1'))).toBe(true)
  })

  it('键位门控：输入框聚焦或模态打开时不抢键', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    expect(paraFocusKeyAllowed(input)).toBe(false)
    const dialog = document.createElement('div')
    dialog.setAttribute('aria-modal', 'true')
    document.body.appendChild(dialog)
    expect(paraFocusKeyAllowed(document.createElement('p'))).toBe(false)
    dialog.remove()
    input.remove()
    expect(paraFocusKeyAllowed(document.createElement('p'))).toBe(true)
  })
})

// ---- F062：全局 j/k 共存（Reader 内逐段优先于「下一篇/上一篇」） ----

describe('F062 — 逐段专注激活时 j/k 截停全局导航（capture 相）', () => {
  it('j 移动当前段且不触发全局 next（冒泡相全局处理器收不到）', () => {
    const { article } = mountArticle()
    let globalNextFired = 0
    const globalHandler = (event: KeyboardEvent) => {
      if (event.key === 'j') globalNextFired += 1
    }
    window.addEventListener('keydown', globalHandler)

    // 模拟 Reader effect 的接线方式：capture 相监听 + stopImmediatePropagation
    const blocks = getParaFocusBlocks(article)
    article.setAttribute('data-lumi-para-focus', 'on')
    const onKey = (event: KeyboardEvent) => {
      if (!paraFocusKeyAllowed(event.target)) return
      if (event.key === 'j' || event.key === 'k') {
        event.preventDefault()
        event.stopImmediatePropagation()
        const next = moveParaFocusIndex(blocks.length, -1, event.key === 'j' ? 1 : -1)
        applyParaFocusIndex(blocks, next)
      }
    }
    window.addEventListener('keydown', onKey, true)

    // 事件目标必须是真实元素（与真实键入一致），冒泡到 window
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }))
    expect(article.querySelector('[data-lumi-para-focus-active]')?.id).toBe('p1')
    expect(globalNextFired).toBe(0)

    window.removeEventListener('keydown', onKey, true)
    window.removeEventListener('keydown', globalHandler)
  })
})

// ---- F076：遮挡模式 ----

describe('F076 — ReadingRuler 遮挡聚焦模式', () => {
  beforeEach(() => {
    localStorage.clear()
    // rAF 同步化（与既有 reading-ruler.test.tsx 同一手法）：
    // pointermove 的节流回调立即执行，测试无需等帧
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', () => {})
  })

  it('默认辅助线模式；遮挡持久化读取（损坏值回退）', () => {
    expect(readRulerMode()).toBe('guide')
    localStorage.setItem(READING_RULER_MODE_KEY, 'occlusion')
    expect(readRulerMode()).toBe('occlusion')
    localStorage.setItem(READING_RULER_MODE_KEY, 'bogus')
    expect(readRulerMode()).toBe('guide')
  })

  it('遮挡模式渲染上下遮罩（尺外内容被盖住，当前行窗口保留）', () => {
    localStorage.setItem(READING_RULER_MODE_KEY, 'occlusion')
    const { article } = mountArticle()
    render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    fireEvent.pointerMove(article, { clientY: 300 })
    const overlay = document.querySelector('[data-lumi-reading-ruler="true"]')
    expect(overlay?.getAttribute('data-lumi-reading-ruler-mode')).toBe('occlusion')
    expect(document.querySelector('[data-lumi-reading-ruler-mask="top"]')).not.toBeNull()
    expect(document.querySelector('[data-lumi-reading-ruler-mask="bottom"]')).not.toBeNull()
  })

  it('模式并列切换：按钮切到辅助线、m 键切回遮挡（持久化跟随），Esc 关闭', () => {
    localStorage.setItem(READING_RULER_MODE_KEY, 'occlusion')
    const { article } = mountArticle()
    render(<ReadingRuler />)
    fireEvent.click(screen.getByRole('button', { name: '行辅助线' }))
    fireEvent.pointerMove(article, { clientY: 300 })
    // 遮挡 → 辅助线（按钮）
    fireEvent.click(screen.getByRole('button', { name: '辅助线' }))
    expect(document.querySelector('[data-lumi-reading-ruler-mode="guide"]')).not.toBeNull()
    expect(localStorage.getItem(READING_RULER_MODE_KEY)).toBe('guide')
    // 辅助线 → 遮挡（m 键；fireEvent 自包 act，状态同步落地）
    fireEvent.keyDown(window, { key: 'm' })
    expect(document.querySelector('[data-lumi-reading-ruler-mode="occlusion"]')).not.toBeNull()
    expect(localStorage.getItem(READING_RULER_MODE_KEY)).toBe('occlusion')
    // Esc 关闭（开关回到「行辅助线」）
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.getByRole('button', { name: '行辅助线' })).toHaveAttribute('aria-pressed', 'false')
  })
})

// ---- F063：护眼提醒 ----

describe('F063 — ReadingBreakReminder 护眼提醒', () => {
  function stubVisible(value: 'visible' | 'hidden'): void {
    Object.defineProperty(document, 'visibilityState', { value, configurable: true })
  }

  it('45 分钟默认档：可见累计达到间隔后弹非阻塞提示，知道了重置', async () => {
    vi.useFakeTimers()
    stubVisible('visible')
    render(<ReadingBreakReminder minutes={45} />)
    expect(screen.queryByRole('status')).toBeNull()
    // 44:59 未到（advance 需包 act，React 状态更新才在包内落地）
    await act(async () => {
      await vi.advanceTimersByTimeAsync((45 * 60 - 1) * 1000)
    })
    expect(screen.queryByRole('status')).toBeNull()
    // 45:00 触发
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(screen.getByRole('status')).toHaveTextContent('已连续阅读 45 分钟')
    // 知道了 → 关闭并重置（再过 45 分钟才会再次出现）
    fireEvent.click(screen.getByRole('button', { name: '知道了' }))
    expect(screen.queryByRole('status')).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(44 * 60 * 1000)
    })
    expect(screen.queryByRole('status')).toBeNull()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000)
    })
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('0 = 关闭；页面不可见不累计', () => {
    vi.useFakeTimers()
    stubVisible('hidden')
    render(<ReadingBreakReminder minutes={0} />)
    vi.advanceTimersByTime(90 * 60 * 1000)
    expect(screen.queryByRole('status')).toBeNull()
    const { unmount } = render(<ReadingBreakReminder minutes={20} />)
    vi.advanceTimersByTime(60 * 60 * 1000)
    expect(screen.queryByRole('status')).toBeNull()
    unmount()
    stubVisible('visible')
  })
})

// ---- F080：会话时长 ----

describe('F080 — 当前会话阅读时长', () => {
  it('formatSessionDuration：< 1h mm:ss，≥ 1h h:mm:ss，非法输入按 0', () => {
    expect(formatSessionDuration(0)).toBe('00:00')
    expect(formatSessionDuration(65_000)).toBe('01:05')
    expect(formatSessionDuration(3_600_000 + 125_000)).toBe('1:02:05')
    expect(formatSessionDuration(-5)).toBe('00:00')
    expect(formatSessionDuration(Number.NaN)).toBe('00:00')
  })

  it('Aa 面板显示「本次阅读」并随时间刷新', async () => {
    vi.useFakeTimers()
    const startedAt = Date.now()
    render(withQueryClient(<ReaderAaPanel sessionStartedAt={startedAt} />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    const row = document.querySelector('[data-lumi-session-duration]')!
    expect(row).toHaveTextContent('本次阅读')
    expect(row.textContent).toMatch(/00:00/)
    await vi.advanceTimersByTimeAsync(65_000)
    expect(row.textContent).toMatch(/01:05/)
  })

  it('未传 sessionStartedAt 时不显示时长行（既有使用零影响）', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    expect(document.querySelector('[data-lumi-session-duration]')).toBeNull()
  })
})

// ---- F063：设置归一化 ----

describe('F063 — readerBreakReminderMinutes 归一化', () => {
  it('默认 45；档位外回退默认', () => {
    expect(DEFAULT_APP_SETTINGS.readerBreakReminderMinutes).toBe(45)
    expect(normalizeSettings({ readerBreakReminderMinutes: 20 }).readerBreakReminderMinutes).toBe(20)
    expect(normalizeSettings({ readerBreakReminderMinutes: 25 }).readerBreakReminderMinutes).toBe(45)
    expect(normalizeSettings({ readerBreakReminderMinutes: '45' }).readerBreakReminderMinutes).toBe(45)
  })

  it('设置项直连 store', () => {
    useAppSettings.getState().update({ readerBreakReminderMinutes: 30 })
    expect(useAppSettings.getState().settings.readerBreakReminderMinutes).toBe(30)
    useAppSettings.getState().update({ readerBreakReminderMinutes: 0 })
    expect(useAppSettings.getState().settings.readerBreakReminderMinutes).toBe(0)
  })
})
