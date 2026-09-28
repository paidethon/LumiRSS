/** FIX-093 — 移动端侧栏抽屉打开期间：遮罩盖住正文、背景不可交互、
 * 滚动锁定，三者一致；关闭后背景恢复可交互。
 *
 * mobile-navigation.test.tsx 已覆盖 role/aria-modal、滚动锁、焦点 trap
 * 与还焦、遮罩点击/Escape/✕ 关闭；本文件补齐 FIX-093 特有的三条契约：
 *   1. 打开期间背景元素被 Base UI 模态隔离（data-base-ui-inert +
 *      aria-hidden）——点击背景控件不产生任何效果（「背景可被点击」回归）；
 *   2. 遮罩层真实存在于面板之下的视口层（fixed inset-0 全屏覆盖）；
 *   3. 关闭后 inert 解除，背景控件恢复可交互。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { EntryListResponse } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const FEEDS = [
  { title: '示例源 A', feedUrl: 'https://a.example.com/feed.xml', category: null },
]

function entry(ref: string): EntryListResponse['items'][number] {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function mockApi(): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/feeds')) return jsonResponse(FEEDS)
    if (/^\/api\/v1\/entries\/e1\./.test(url)) {
      return jsonResponse({
        entryRef: 'e1.a',
        title: '文章 e1.a',
        feedTitle: '示例源 A',
        author: null,
        url: null,
        publishedAt: null,
        read: false,
        starred: false,
        contentText: '纯文本正文',
        contentHtml: null,
      })
    }
    if (url.startsWith('/api/v1/entries')) {
      return jsonResponse({ items: [entry('e1.a')], nextCursor: null })
    }
    throw new Error(`unexpected fetch: ${url}`)
  })
}

const menuButton = () => document.querySelector<HTMLButtonElement>('[aria-label="打开导航"]')!
const drawer = () => document.getElementById('mobile-navigation-drawer')

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(async () => {
  useReaderUi.setState({
    view: 'all',
    scope: { kind: 'all' },
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })
  // Sheet / MobileNavigationDrawer 是 lazy 分包：预解析保证打开后的同步
  // 结构断言确定性成立（与 mobile-navigation.test.tsx 同一约定）。
  await import('../components/ui/Sheet')
  await import('../components/MobileNavigationDrawer')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FIX-093: 抽屉打开期间遮罩/背景交互/滚动锁一致', () => {
  it('打开时背景被 inert 隔离且点击无效；全屏遮罩存在于面板之下；关闭后背景恢复', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()

    // 背景控件（顶栏菜单钮）在抽屉打开前可正常交互
    expect(document.querySelector('[data-base-ui-inert]')).toBeNull()

    fireEvent.click(menuButton())
    await waitFor(() => {
      expect(drawer()).not.toBeNull()
    })
    const panel = drawer()!
    expect(panel).toHaveAttribute('role', 'dialog')

    // 遮罩：全屏 fixed inset-0 层（Portal 内、面板之下），正文被盖住
    const backdrop = document.querySelector('.fixed.inset-0')
    expect(backdrop).not.toBeNull()

    // 背景被模态隔离：Base UI inert + aria-hidden
    await waitFor(() => {
      expect(document.querySelector('[data-base-ui-inert]')).not.toBeNull()
    })
    expect(menuButton().closest('[data-base-ui-inert]')).not.toBeNull()
    expect(menuButton().closest('[aria-hidden="true"]')).not.toBeNull()

    // 行为契约：点击背景控件不产生效果（aria-expanded 仍是 true，不轮转）
    const expandedBefore = menuButton().getAttribute('aria-expanded')
    fireEvent.click(menuButton())
    expect(menuButton().getAttribute('aria-expanded')).toBe(expandedBefore)

    // 关闭后 inert 解除，背景恢复可交互
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => {
      expect(drawer()).toBeNull()
    })
    await waitFor(() => {
      expect(document.querySelector('[data-base-ui-inert]')).toBeNull()
    })
    fireEvent.click(menuButton())
    await waitFor(() => {
      expect(menuButton().getAttribute('aria-expanded')).toBe('true')
    })
  })

  it('打开时 body 滚动锁定（与遮罩/inert 同一生命周期）', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderApp()
    await waitFor(() => {
      expect(document.body.style.overflowY).not.toBe('hidden')
    })
    fireEvent.click(menuButton())
    await waitFor(() => {
      expect(document.body.style.overflowY).toBe('hidden')
    })
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
    await waitFor(() => {
      expect(drawer()).toBeNull()
    })
    await waitFor(() => {
      expect(document.body.style.overflowY).not.toBe('hidden')
    })
  })
})
