/** F11–F25 Reader 级集成测试（jsdom）。
 *
 * 每项功能：真实入口（工具栏按钮 / 开关 / 滚动）+ 行为断言 + 失败与
 * 降级路径。语音 / 分享 / 打印全部 mock——证明接线，非平台能力验证。
 * 自动已读豁免用 MockIO + fake timers 证明（F18）；F25 的回顶/恢复
 * 走同一 noteProgrammaticScroll 机制（行为断言见各用例注释）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Reader from '../components/Reader'
import type { EntryDetail } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { FINISH_READ_DWELL_MS } from '../lib/finish-read'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: '作者甲',
    url: 'https://example.com/a',
    publishedAt: '2026-08-28T10:00:00Z',
    read: false,
    starred: false,
    contentText: '纯文本正文 A',
    contentHtml: '<p>富文本正文 A</p>',
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function noContent(): Response {
  return new Response(null, { status: 204 })
}

type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

function mockApi(handlers: Array<{ when: (url: string, init?: RequestInit) => boolean; respond: FetchHandler }>) {
  return vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    for (const h of handlers) {
      if (h.when(url, init)) return h.respond(url, init)
    }
    throw new Error(`unexpected fetch: ${url} ${init?.method ?? 'GET'}`)
  })
}

const detailRoute = (ref: string, body: unknown, status = 200) => ({
  when: (url: string, init?: RequestInit) =>
    (init?.method ?? 'GET') === 'GET' && url === `/api/v1/entries/${ref}`,
  respond: () => jsonResponse(body, status),
})

const patchRoute = (fn: FetchHandler) => ({
  when: (url: string, init?: RequestInit) => init?.method === 'PATCH' && url.includes('/state'),
  respond: fn,
})

function renderReader(queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <Reader />
      </QueryClientProvider>,
    ),
  }
}

function scroller(): HTMLElement {
  return document.querySelector('.lumi-reader-article')!.parentElement!
}

function stubScrollerLayout(
  node: HTMLElement,
  { scrollHeight, clientHeight }: { scrollHeight: number; clientHeight: number },
) {
  Object.defineProperty(node, 'scrollHeight', { value: scrollHeight, configurable: true })
  Object.defineProperty(node, 'clientHeight', { value: clientHeight, configurable: true })
  Object.defineProperty(node, 'scrollTop', { value: 0, writable: true, configurable: true })
}

/** 给 navigator 挂可删除的 mock 属性（share/clipboard 等只读成员）。 */
function stubNavigatorMember(name: string, value: unknown): void {
  Object.defineProperty(window.navigator, name, {
    value,
    configurable: true,
  })
}

beforeEach(async () => {
  // Aa 面板底部 Sheet 是 lazy 分包（bundle guard）：预解析 chunk，让
  // 打开面板后的同步结构断言确定性成立（异步时序适配，语义不变）。
  await import('../components/ui/Sheet')
  useReaderUi.setState({ view: 'all', scope: { kind: 'all' }, selectedEntryRef: null })
  useAppSettings.setState({
    settings: {
      ...useAppSettings.getState().settings,
      readerShowReadingProgress: true,
      readerPagedMode: false,
      readerCodeWrap: false,
      readerImageMode: 'all',
      readerAutoMarkRead: false,
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  localStorage.clear()
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav.share
  delete nav.clipboard
})

// ---- F11 阅读进度条 ----

describe('F11 — 阅读进度条', () => {
  it('滚动 → 顶部 3px 进度条按比例显示；回到顶部隐藏；开关关闭不渲染', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    stubScrollerLayout(scroller(), { scrollHeight: 1200, clientHeight: 800 })
    scroller().scrollTop = 100 // max = 400 → 25%
    fireEvent.scroll(scroller())
    await waitFor(() => {
      const bar = document.querySelector('[data-lumi-progress-bar]') as HTMLElement | null
      expect(bar).not.toBeNull()
      expect(bar).toHaveStyle({ width: '25%' })
    })

    scroller().scrollTop = 0
    fireEvent.scroll(scroller())
    await waitFor(() => {
      expect(document.querySelector('[data-lumi-progress]')).toBeNull()
    })

    // 开关关闭（settings 同一真源）→ 即时移除
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerShowReadingProgress: false },
    })
    scroller().scrollTop = 200
    fireEvent.scroll(scroller())
    await waitFor(() => {
      expect(document.querySelector('[data-lumi-progress]')).toBeNull()
    })
  })
})

// ---- F13 文内查找 ----

describe('F13 — 文内查找', () => {
  it('工具栏入口打开查找条；命中计数 n/m；无结果诚实显示；关闭无残留', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p>术语一</p><p>术语二</p><p>别的段落</p>',
      })),
    ]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    // 入口：ReaderHeader 工具栏（jsdom 无 CSS.highlights → 降级路径）
    fireEvent.click(screen.getByRole('button', { name: '文内查找' }))
    // 查找条为懒加载 chunk：等待挂载（修复慢机竞态，与 bcfe0a6 同类）
    const input = await screen.findByLabelText('查找正文')
    fireEvent.change(input, { target: { value: '术语' } })
    expect(await screen.findByText('1/2 处命中')).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '不存在的词' } })
    expect(await screen.findByText('无结果')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '关闭查找' }))
    await waitFor(() => {
      expect(screen.queryByRole('search', { name: '文内查找' })).toBeNull()
    })
  })
})

// ---- F14 图片灯箱 ----

describe('F14 — 图片灯箱', () => {
  it('正文图片接线 zoom-in；点击打开；Esc 关闭后焦点返回图片', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p>开头</p><p><img src="https://example.com/pic.png" alt="示意图"></p><p>结尾</p>',
      })),
    ]))
    renderReader()
    const img = (await screen.findByRole('img', { name: '示意图' })) as HTMLImageElement
    // 装饰：防重复标记 + zoom-in + 可聚焦（焦点归还前提）
    expect(img.dataset.lumiLightboxReady).toBe('true')
    expect(img.style.cursor).toBe('zoom-in')
    expect(img.getAttribute('tabindex')).toBe('-1')

    fireEvent.click(img)
    const dialog = await screen.findByRole('dialog', { name: '图片查看' })
    expect(dialog).toHaveFocus()
    // 单图：无计数/切换控件；缩放控件存在（1–4x 接线）
    expect(document.querySelector('[data-lumi-lightbox-counter]')).toBeNull()
    expect(screen.getByRole('button', { name: '放大' })).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '图片查看' })).toBeNull()
    })
    // 关闭后焦点返回触发图片
    expect(document.activeElement).toBe(img)
  })

  it('hidden 模式不接线（无标记、点击不开、不偷偷加载）；单篇覆盖后恢复', async () => {
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerImageMode: 'hidden' },
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p><img src="https://example.com/pic.png" alt="示意图"></p>',
      })),
    ]))
    renderReader()
    const img = await screen.findByRole('img', { name: '示意图' }) as HTMLImageElement
    // 省流模式已摘除 src（不偷偷加载），且无灯箱接线标记
    expect(img.getAttribute('src')).toBeNull()
    expect(img.dataset.lumiLightboxReady).toBeUndefined()

    fireEvent.click(img)
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '图片查看' })).toBeNull()
    })

    // 单篇覆盖（点「加载本文图片」）→ src 恢复 + 灯箱接线
    fireEvent.click(screen.getByRole('button', { name: '加载本文图片' }))
    const restored = (await screen.findByRole('img', { name: '示意图' })) as HTMLImageElement
    expect(restored.getAttribute('src')).toBe('https://example.com/pic.png')
    await waitFor(() => {
      expect(restored.dataset.lumiLightboxReady).toBe('true')
    })
  })
})

// ---- F15 代码换行 ----

describe('F15 — 代码自动换行', () => {
  it('Aa 面板开关切换 settings → html[data-code-wrap] on/off', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<pre><code>const a = 1</code></pre>',
      })),
    ]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })
    // 默认 off（保持横向滚动）
    expect(document.documentElement.dataset.codeWrap).toBe('off')

    // Aa 面板（jsdom isMobile → 底部 Sheet 路径）里的开关
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    const codeWrapSwitch = screen.getByRole('switch', { name: '代码自动换行' })
    expect(codeWrapSwitch).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(codeWrapSwitch)
    await waitFor(() => {
      expect(useAppSettings.getState().settings.readerCodeWrap).toBe(true)
      expect(document.documentElement.dataset.codeWrap).toBe('on')
    })

    fireEvent.click(screen.getByRole('switch', { name: '代码自动换行' }))
    await waitFor(() => {
      expect(useAppSettings.getState().settings.readerCodeWrap).toBe(false)
      expect(document.documentElement.dataset.codeWrap).toBe('off')
    })
  })
})

// ---- F16 表格展开 ----

describe('F16 — 表格展开', () => {
  it('过宽表格（data-table-wide 标记路径）出现展开按钮；面板完整查看；Esc 关闭还原滚动', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml:
          '<table data-table-wide><tr><td>宽表格单元格</td></tr></table>' +
          '<table><tr><td>窄表格</td></tr></table>',
      })),
    ]))
    renderReader()
    await screen.findByText('宽表格单元格')

    // 只有宽表格包了「展开查看」按钮
    const expandButtons = screen.getAllByRole('button', { name: '展开表格' })
    expect(expandButtons).toHaveLength(1)

    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })
    scroller().scrollTop = 444
    fireEvent.click(expandButtons[0]!)

    const dialog = await screen.findByRole('dialog', { name: '表格查看' })
    // 面板内是语义表格克隆（table/th/td 保留、横向可滚容器）
    const panelTable = dialog.querySelector('[data-lumi-table-host] table')
    expect(panelTable).not.toBeNull()
    expect(panelTable!.textContent).toContain('宽表格单元格')

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '表格查看' })).toBeNull()
    })
    // 关闭后滚动位置回到原处
    expect(scroller().scrollTop).toBe(444)
  })

  it('scrollWidth 判定路径：stub 布局后过宽表格自动获得展开按钮', async () => {
    // jsdom 无布局：对 HTMLTableElement.prototype 注入实测尺寸
    Object.defineProperty(HTMLTableElement.prototype, 'scrollWidth', {
      configurable: true,
      get: () => 800,
    })
    Object.defineProperty(HTMLTableElement.prototype, 'clientWidth', {
      configurable: true,
      get: () => 100,
    })
    try {
      useReaderUi.setState({ selectedEntryRef: 'e1.a' })
      vi.stubGlobal('fetch', mockApi([
        detailRoute('e1.a', detail({
          contentHtml: '<table><tr><td>T1</td></tr></table><table><tr><td>T2</td></tr></table>',
        })),
      ]))
      renderReader()
      await screen.findByText('T1')
      // 800 > 100 + 24 → 两张表都判定过宽
      await waitFor(() => {
        expect(screen.getAllByRole('button', { name: '展开表格' })).toHaveLength(2)
      })
    } finally {
      delete (HTMLTableElement.prototype as { scrollWidth?: unknown }).scrollWidth
      delete (HTMLTableElement.prototype as { clientWidth?: unknown }).clientWidth
    }
  })
})

// ---- F17 按屏翻页 ----

describe('F17 — 按屏翻页', () => {
  it('开关关闭不渲染按钮', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })
    expect(screen.queryByRole('button', { name: '上一屏' })).toBeNull()
    expect(screen.queryByRole('button', { name: '下一屏' })).toBeNull()
  })

  it('开启后右下角竖排按钮；顶/底边界 disabled；点击 ±90% 视口平滑翻页', async () => {
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerPagedMode: true },
    })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    const up = screen.getByRole('button', { name: '上一屏' })
    const down = screen.getByRole('button', { name: '下一屏' })
    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })

    // 初始在顶部：上一屏禁用；首次滚动测量后下一屏可用
    expect(up).toBeDisabled()
    fireEvent.scroll(scroller())
    await waitFor(() => expect(down).not.toBeDisabled())

    // 下一屏：0 + 600×0.9 = 540
    fireEvent.click(down)
    await waitFor(() => expect(scroller().scrollTop).toBe(540))

    // 到底：下一屏禁用、上一屏可用
    scroller().scrollTop = 3400
    fireEvent.scroll(scroller())
    await waitFor(() => expect(down).toBeDisabled())
    expect(up).not.toBeDisabled()

    // 上一屏：3400 - 540 = 2860
    fireEvent.click(up)
    await waitFor(() => expect(scroller().scrollTop).toBe(2860))
  })
})

// ---- F18 自动滚屏（含 finish-read 每帧豁免证明） ----

type Record_ = IntersectionObserverEntry

class MockIO {
  static instances: MockIO[] = []
  cb: IntersectionObserverCallback
  root: Document | Element | null
  targets = new Set<Element>()
  constructor(cb: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.cb = cb
    this.root = options?.root ?? null
    MockIO.instances.push(this)
  }
  observe(el: Element) {
    this.targets.add(el)
  }
  unobserve(el: Element) {
    this.targets.delete(el)
  }
  disconnect() {
    this.targets.clear()
  }
  trigger(el: Element, isIntersecting: boolean) {
    this.cb(
      [{ target: el, isIntersecting } as unknown as Record_],
      this as unknown as IntersectionObserver,
    )
  }
}

describe('F18 — 自动滚屏', () => {
  it('开始 → scrollTop 每帧增长且不误触发自动已读；暂停/继续/停止状态切换', async () => {
    vi.useFakeTimers()
    MockIO.instances = []
    vi.stubGlobal('IntersectionObserver', MockIO as unknown as typeof IntersectionObserver)

    let patchCalls = 0
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerAutoMarkRead: true },
    })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail()),
      patchRoute(() => {
        patchCalls += 1
        return noContent()
      }),
    ]))
    renderReader()
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    screen.getByText('文章 A') // 内容已渲染（供 scroller() 取容器）
    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })

    // 末尾哨兵可见（滚动帧内 finish-read 会重测并评估）
    const sentinel = document.querySelector('[data-finish-sentinel]') as HTMLElement
    const io = MockIO.instances.find((i) => i.targets.has(sentinel))
    expect(io).toBeDefined()
    act(() => {
      io!.trigger(sentinel, true)
    })

    // 入口：更多操作菜单 → 自动滚屏
    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })
    fireEvent.click(screen.getByRole('menuitem', { name: '自动滚屏' }))

    // 状态 chip 出现；rAF 每帧 +2px（中速默认）
    expect(document.querySelector('[data-lumi-autoscroll-chip]')).not.toBeNull()
    expect(screen.getByText('自动滚屏 · 中')).toBeInTheDocument()
    for (let i = 0; i < 25; i += 1) {
      act(() => {
        vi.advanceTimersByTime(16)
        scroller().dispatchEvent(new Event('scroll'))
      })
    }
    const progressed = scroller().scrollTop
    // 25 帧 × 2px = 50 ≥ requiredProgress(40)：若豁免失效，停留判定已达标
    expect(progressed).toBeGreaterThanOrEqual(40)

    // 关键证明：自动滚屏期间哨兵一直可见 + 停留计时充足，但零 PATCH——
    // 每帧 noteProgrammaticScroll() 的豁免生效（不豁免时最后一次滚动
    // 评估即满足条件，DWELL 到点必然派发）。
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS + 500)
    })
    expect(patchCalls).toBe(0)

    // 暂停：帧不再推进；chip 状态诚实显示
    const afterDwell = scroller().scrollTop
    fireEvent.click(screen.getByRole('button', { name: '暂停自动滚屏' }))
    expect(screen.getByText('自动滚屏 · 已暂停')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(16 * 10)
    })
    expect(scroller().scrollTop).toBe(afterDwell)

    // 继续
    fireEvent.click(screen.getByRole('button', { name: '继续自动滚屏' }))
    act(() => {
      vi.advanceTimersByTime(16 * 10)
    })
    expect(scroller().scrollTop).toBeGreaterThan(afterDwell)

    // 停止：chip 消失、滚动停止
    fireEvent.click(screen.getByRole('button', { name: '停止自动滚屏' }))
    expect(document.querySelector('[data-lumi-autoscroll-chip]')).toBeNull()
    const stoppedAt = scroller().scrollTop
    act(() => {
      vi.advanceTimersByTime(16 * 10)
    })
    expect(scroller().scrollTop).toBe(stoppedAt)

    // 对照组：豁免窗口过期后，用户手动滚动 + 停留 → 派发（证明上述
    // 零 PATCH 来自豁免而非判定失效）。
    act(() => {
      vi.advanceTimersByTime(500)
      scroller().scrollTop = stoppedAt + 100
      scroller().dispatchEvent(new Event('scroll'))
    })
    act(() => {
      vi.advanceTimersByTime(FINISH_READ_DWELL_MS + 100)
    })
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(patchCalls).toBe(1)

    vi.useRealTimers()
  })

  it('速度三档可切换（慢/中/快 → 每帧 1/2/4px）', async () => {
    vi.useFakeTimers()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    screen.getByText('文章 A')
    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })
    fireEvent.click(screen.getByRole('menuitem', { name: '自动滚屏' }))
    expect(document.querySelector('[data-lumi-autoscroll-chip]')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '速度慢' }))
    expect(screen.getByText('自动滚屏 · 慢')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(16 * 5)
    })
    expect(scroller().scrollTop).toBe(5)

    fireEvent.click(screen.getByRole('button', { name: '速度快' }))
    expect(screen.getByText('自动滚屏 · 快')).toBeInTheDocument()
    act(() => {
      vi.advanceTimersByTime(16 * 5)
    })
    expect(scroller().scrollTop).toBe(5 + 20)

    vi.useRealTimers()
  })
})

// ---- F19 朗读（mock speechSynthesis：证明接线，非平台能力验证） ----

class MockUtterance {
  text: string
  lang = ''
  voice: unknown = null
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

function stubSpeech() {
  const speak = vi.fn()
  const cancel = vi.fn()
  const pause = vi.fn()
  const resume = vi.fn()
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => [{ lang: 'zh-CN', name: 'zh' } as SpeechSynthesisVoice],
    speak,
    cancel,
    pause,
    resume,
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return { speak, cancel, pause, resume }
}

describe('F19 — 朗读', () => {
  it('能力缺失 → 按钮诚实禁用 + 原因（不假装可派发）', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })
    const button = screen.getByRole('button', { name: '朗读' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title')
  })

  it('开始朗读调用 speak（正文文本、中文声音）；暂停/继续/停止接线正确', async () => {
    const speech = stubSpeech()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p>第一段内容</p><p>第二段内容</p>',
      })),
    ]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    expect(speech.speak).toHaveBeenCalledTimes(1)
    const utterance = speech.speak.mock.calls[0]![0] as MockUtterance
    expect(utterance.text).toContain('第二段内容')
    expect(utterance.voice).toMatchObject({ lang: 'zh-CN' })
    expect(utterance.rate).toBe(1)

    // 朗读中 → 暂停按钮出现（图标按钮 label 变化）
    fireEvent.click(screen.getByRole('button', { name: '暂停朗读' }))
    expect(speech.pause).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '继续朗读' }))
    expect(speech.resume).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '停止朗读' }))
    expect(speech.cancel).toHaveBeenCalled()
  })

  it('utterance onerror → 行内诚实报错并复位', async () => {
    const speech = stubSpeech()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    const utterance = speech.speak.mock.calls[0]![0] as MockUtterance
    utterance.onerror?.()
    expect(await screen.findByText('朗读失败，请重试。')).toBeInTheDocument()
    // 复位为 idle：再次出现「朗读」入口
    expect(screen.getByRole('button', { name: '朗读' })).toBeInTheDocument()
  })

  it('语速 segmented：切换后 speak 的 rate 变化', async () => {
    const speech = stubSpeech()
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).rate).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: '1.5x' }))
    // 朗读中调速 = 按新语速重读（重新 speak）
    expect(speech.speak).toHaveBeenCalledTimes(2)
    expect((speech.speak.mock.calls[1]![0] as MockUtterance).rate).toBe(1.5)
  })
})

// ---- F21 分享（mock navigator.share：证明接线，非平台能力验证） ----

describe('F21 — 分享', () => {
  it('无 share 能力 → 直接「复制链接」行为 + 「链接已复制」反馈', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('clipboard', { writeText })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '复制链接' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('https://example.com/a')
    })
    expect(await screen.findByText('链接已复制')).toBeInTheDocument()
  })

  it('share 可用 → 系统分享（title + 安全 url），成功时不回退复制', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    const writeText = vi.fn()
    stubNavigatorMember('share', share)
    stubNavigatorMember('clipboard', { writeText })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '分享' }))
    await waitFor(() => {
      expect(share).toHaveBeenCalledWith({
        title: '文章 A',
        url: 'https://example.com/a',
      })
    })
    expect(writeText).not.toHaveBeenCalled()
  })

  it('用户取消（AbortError）静默：不复制、无报错', async () => {
    const share = vi.fn().mockRejectedValue(Object.assign(new Error('cancel'), { name: 'AbortError' }))
    const writeText = vi.fn()
    stubNavigatorMember('share', share)
    stubNavigatorMember('clipboard', { writeText })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '分享' }))
    await waitFor(() => expect(share).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 20))
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.queryByText('链接已复制')).toBeNull()
  })

  it('share 其它失败 → 回退复制链接 + 「链接已复制」', async () => {
    const share = vi.fn().mockRejectedValue(new Error('share unavailable'))
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('share', share)
    stubNavigatorMember('clipboard', { writeText })
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '分享' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('https://example.com/a')
    })
    expect(await screen.findByText('链接已复制')).toBeInTheDocument()
  })
})

// ---- F22 导出（stub URL.createObjectURL） ----

describe('F22 — 导出 Markdown / HTML', () => {
  function stubObjectUrls() {
    const created: Blob[] = []
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn((blob: Blob) => {
        created.push(blob)
        return 'blob:mock'
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    })
    return created
  }

  it('导出 Markdown：createObjectURL 被调、内容含标题与分段', async () => {
    const created = stubObjectUrls()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p>段落甲</p>',
        contentText: '段落甲\n\n段落乙',
      })),
    ]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '导出 Markdown' }))

    await waitFor(() => expect(created).toHaveLength(1))
    expect(clickSpy).toHaveBeenCalled()
    const text = await created[0]!.text()
    expect(text).toContain('# 文章 A')
    expect(text).toContain('原文链接：https://example.com/a')
    expect(text).toContain('段落甲\n\n段落乙')
    clickSpy.mockRestore()
  })

  it('导出 HTML：createObjectURL 被调、含标题、script 被剥掉', async () => {
    const created = stubObjectUrls()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([
      detailRoute('e1.a', detail({
        contentHtml: '<p>富文本</p><script>alert(1)</script>',
      })),
    ]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '导出 HTML' }))

    await waitFor(() => expect(created).toHaveLength(1))
    const text = await created[0]!.text()
    expect(text).toContain('<title>文章 A</title>')
    expect(text).toContain('<meta charset="utf-8">')
    expect(text).toContain('富文本')
    expect(text).not.toContain('alert(1)')
    clickSpy.mockRestore()
  })
})

// ---- F23 打印（stub window.print：证明接线） ----

describe('F23 — 打印', () => {
  it('工具栏打印按钮 → window.print() 被调用', async () => {
    const printMock = vi.fn()
    vi.stubGlobal('print', printMock)
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '打印' }))
    expect(printMock).toHaveBeenCalledTimes(1)
  })
})

// ---- F24 复制引用 ----

describe('F24 — 复制引用', () => {
  it('有选区 → Markdown 格式（标题/来源/链接/ > 引文）写入剪贴板', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('clipboard', { writeText })
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '  这是一段被选中的引文  ',
    } as Selection)
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '复制引用' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制为 Markdown' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        '文章 A\n示例源\nhttps://example.com/a\n\n> 这是一段被选中的引文',
      )
    })
  })

  it('纯文本格式：引文不带 > 前缀', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigatorMember('clipboard', { writeText })
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '引文内容',
    } as Selection)
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '复制引用' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制为纯文本' }))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        '文章 A\n示例源\nhttps://example.com/a\n\n引文内容',
      )
    })
  })

  it('无选区 → 仅标题/来源/链接；剪贴板失败 → 只读文本框诚实降级', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard blocked'))
    stubNavigatorMember('clipboard', { writeText })
    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => '',
    } as Selection)
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })

    fireEvent.click(screen.getByRole('button', { name: '复制引用' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制为纯文本' }))

    const textarea = await screen.findByLabelText(
      '复制失败的引用文本（可手动复制）',
    ) as HTMLTextAreaElement
    expect(textarea.value).toBe('文章 A\n示例源\nhttps://example.com/a')
    expect(screen.getByRole('button', { name: '全选' })).toBeInTheDocument()
  })
})

// ---- F25 回到顶部 / 返回刚才位置 ----

describe('F25 — 回到顶部 / 返回刚才位置', () => {
  it('滚动 >600px 出现「回到顶部」；点击归零并切换为「返回刚才位置」；恢复原位置', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })
    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })

    // 未超过阈值：按钮不出现
    scroller().scrollTop = 500
    fireEvent.scroll(scroller())
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '回到顶部' })).toBeNull()
    })

    scroller().scrollTop = 700
    fireEvent.scroll(scroller())
    const backTop = await screen.findByRole('button', { name: '回到顶部' })

    // 回到顶部：scrollTop=0，按钮切换为「返回刚才位置」
    fireEvent.click(backTop)
    expect(scroller().scrollTop).toBe(0)
    const backToPosition = await screen.findByRole('button', { name: '返回刚才位置' })

    // 恢复：回到 700，按钮切回「回到顶部」
    fireEvent.click(backToPosition)
    expect(scroller().scrollTop).toBe(700)
    expect(await screen.findByRole('button', { name: '回到顶部' })).toBeInTheDocument()
  })

  it('用户再次滚动重置为「回到顶部」；到底部隐藏', async () => {
    useReaderUi.setState({ selectedEntryRef: 'e1.a' })
    vi.stubGlobal('fetch', mockApi([detailRoute('e1.a', detail())]))
    renderReader()
    await screen.findByText('文章 A', {}, { timeout: 5000 })
    stubScrollerLayout(scroller(), { scrollHeight: 4000, clientHeight: 600 })

    scroller().scrollTop = 800
    fireEvent.scroll(scroller())
    await screen.findByRole('button', { name: '回到顶部' })

    // 用户滚动（重置语义：仍显示回到顶部，保存位置作废）
    scroller().scrollTop = 900
    fireEvent.scroll(scroller())
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '回到顶部' })).toBeInTheDocument()
    })

    // 到底隐藏
    scroller().scrollTop = 3400
    fireEvent.scroll(scroller())
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '回到顶部' })).toBeNull()
    })
  })

  // 注：回顶/恢复调用 noteProgrammaticScroll() 的豁免机制与 F18 的
  // 每帧调用走同一稳定回调（finishRead.noteProgrammaticScroll），其
  // 「程序性滚动不计主动推进」的行为已由 F18 用例的零 PATCH 断言证明；
  // 回顶/恢复的目标位置必然 ≤ 用户已到过的 maxTop（单调上界），在
  // patch 层面不可区分，故此处以滚动位置行为为准。
})
