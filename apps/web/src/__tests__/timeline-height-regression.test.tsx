/** 回归测试 — 移动端 Timeline 占满可用高度（0011 阻断修复）。
 *
 * 根因：Timeline section 曾无条件 inline flexBasis=settings.timelineWidth；
 * <1024px 时 main 为 flex-col，flexBasis 变成高度，把文章列表锁死在
 * 360–460px（390×844 实测 400px，与 main 底部间出现 333px 空白）。
 *
 * 修复：CSS 变量 --lumi-timeline-width + 响应式 flex 类——
 * 移动端 w-full + flex-1（占满剩余高度）；lg 断点才应用栏宽。
 *
 * jsdom 不计算布局，本文件断言 DOM 语义（class/inline style）；
 * 真实尺寸断言见浏览器验证（Gate 报告）。 */

import { act, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

function mockApi() {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
    if (url.startsWith('/api/v1/entries')) {
      // 详情请求（选中文章后 Reader 拉取）：返回合法最小 detail，避免
      // 并发下其他文件的 fetch mock 污染导致 ArticleContent 崩溃
      if (/\/api\/v1\/entries\/[^/]+$/.test(url)) {
        return jsonResponse({
          entryRef: 'e1.x', title: '文章', feedTitle: '源', author: null,
          url: null, publishedAt: null, read: false, starred: false,
          contentText: '正文', contentHtml: null,
        })
      }
      return jsonResponse({ items: [], nextCursor: null } satisfies EntryListResponse)
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
}

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>,
  )
}

/** main 内的 Timeline section：含 lg:basis- 栏宽类（未折叠）或
 * lg:!max-w-14（折叠态，0011 修正补充后保留窄栏）的那个。 */
function timelineSection(): HTMLElement {
  const sections = document.querySelectorAll('main > section')
  const el = Array.from(sections).find((s) =>
    s.className.includes('lg:basis-[var(--lumi-timeline-width)]'),
  )
  if (!el) throw new Error('Timeline section not found')
  return el as HTMLElement
}

beforeEach(() => {
  useReaderUi.setState({ section: 'home', view: 'all', scope: { kind: 'all' }, selectedEntryRef: null, mobileSidebarOpen: false })
  useAppSettings.getState().reset()
  vi.stubGlobal('fetch', mockApi())
})

describe('Timeline 响应式布局（阻断修复回归）', () => {
  it('不再有无条件的 inline flexBasis/flexGrow/flexShrink（flexBasis 会锁移动端高度）', () => {
    renderApp()
    const section = timelineSection()
    const style = section.getAttribute('style') ?? ''
    expect(style).not.toContain('flex-basis')
    expect(style).not.toContain('flex-grow')
    expect(style).not.toContain('flex-shrink')
    // inline style 只携带 CSS 变量（桌面栏宽由 lg 断点消费）
    expect(style).toContain('--lumi-timeline-width')
    expect(style).toContain('400px') // 默认 timelineWidth
  })

  it('移动端存在 flex-1 + w-full（占满 main 剩余高度与宽度）；桌面栏宽仅在 lg 类', () => {
    renderApp()
    const cls = timelineSection().className
    // 移动端：占满剩余高度 + 全宽
    expect(cls).toContain('flex-1')
    expect(cls).toContain('w-full')
    expect(cls).toContain('min-h-0')
    expect(cls).toContain('min-w-0')
    // 桌面：栏宽通过 lg: 断点类 + CSS 变量（不在 inline style 里锁高度）
    expect(cls).toContain('lg:basis-[var(--lumi-timeline-width)]')
    expect(cls).toContain('lg:flex-none')
    expect(cls).toContain('lg:w-auto')
  })

  it('timelineWidth 变化 → CSS 变量更新（拖拽调宽仍驱动桌面栏宽）', async () => {
    renderApp()
    await act(async () => {
      useAppSettings.getState().update({ timelineWidth: 432 })
    })
    const style = timelineSection().getAttribute('style') ?? ''
    expect(style).toContain('--lumi-timeline-width: 432px')
  })

  it('隐藏态：Timeline 完全退出桌面布局列（§26，无窄栏残留）', async () => {
    renderApp()
    await act(async () => {
      useAppSettings.getState().update({ timelineCollapsed: true })
    })
    // 0011 §25/§26：隐藏 = lg:hidden（桌面不占任何布局空间），
    // 不再是窄栏（max-w-14 已删除）
    const cls = timelineSection().className
    expect(cls).toContain('lg:hidden')
    expect(cls).not.toContain('max-w-14')
  })
})

describe('Timeline Flex 祖先链 min-h-0（滚动不争抢）', () => {
  it('main 与 App 根均保留 min-h-0 / 高度约束', () => {
    renderApp()
    const main = document.querySelector('main')!
    expect(main.className).toContain('min-h-0')
    expect(main.className).toContain('flex-1')
    const root = main.parentElement!
    expect(root.className).toContain('h-dvh')
  })

  it('切换 view / feed / section 后 Timeline 布局类不回退', async () => {
    renderApp()
    const before = timelineSection().className
    await act(async () => {
      useReaderUi.getState().selectView('unread')
    })
    expect(timelineSection().className).toBe(before)
    await act(async () => {
      useReaderUi.getState().selectSection('favorites')
    })
    // section != home：移动端隐藏但 flex-1 等基础布局类不变
    expect(timelineSection().className).toContain('max-lg:hidden')
    expect(timelineSection().className).toContain('flex-1')
    await act(async () => {
      useReaderUi.getState().selectSection('home')
    })
  })

  it('Reader 打开时 Timeline 仍渲染（lg:flex）——全屏阅读语义不回归', async () => {
    renderApp()
    // 无文章可点，直接设状态验证类语义
    await act(async () => {
      useReaderUi.getState().selectEntry('e1.x')
    })
    const cls = timelineSection().className
    expect(cls).toContain('hidden')
    expect(cls).toContain('lg:flex')
    await act(async () => {
      useReaderUi.getState().selectEntry(null)
    })
  })
})
