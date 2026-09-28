/** FIX-251 — 全局窗口监听在组件卸载后清除：反复进入页面不放大订阅数。
 *
 * 契约：任何页面级组件注册的 window 监听（自定义事件 / online 等），
 * 每次 mount ↔ unmount 循环后净增量必须为 0——监听器泄漏会让同一
 * 事件被处理 N 次（状态更新被放大 N 倍）。
 *
 * 基线现状（BASELINE_OK 验证）：代码库无 window 'message' 监听；
 * 页面级 window 监听（SearchPage 的 lumirss-open-saved-view、
 * LoginScreen 的 online）均已在 effect 返回值中 removeEventListener。
 * 本文件对真实组件做 3 轮 mount/unmount 的净增量断言。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SearchPage from '../components/pages/SearchPage'
import LoginScreen from '../components/LoginScreen'
import { useSearchState } from '../store/search-state'
import { useReaderUi } from '../store/reader-ui'
import { useSearchBasket } from '../store/search-basket'

type Counts = Map<string, { added: number; removed: number }>

function spyWindowListeners(): Counts {
  const counts: Counts = new Map()
  const entryOf = (type: string) => {
    let entry = counts.get(type)
    if (entry === undefined) {
      entry = { added: 0, removed: 0 }
      counts.set(type, entry)
    }
    return entry
  }
  const originalAdd = window.addEventListener.bind(window)
  const originalRemove = window.removeEventListener.bind(window)
  vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    entryOf(String(type)).added += 1
    return originalAdd(type, listener, options)
  })
  vi.spyOn(window, 'removeEventListener').mockImplementation((type, listener, options) => {
    entryOf(String(type)).removed += 1
    originalRemove(type, listener, options)
  })
  return counts
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  useSearchState.getState().clear()
  useReaderUi.setState({ selectedEntryRef: null, section: 'home' })
  useSearchBasket.getState().reset()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/v1/search/views')) return jsonResponse({ items: [] })
      if (url.startsWith('/api/v1/workspaces')) return jsonResponse({ items: [] })
      if (url.startsWith('/api/v1/feeds')) return jsonResponse([])
      if (url.startsWith('/api/v1/subscriptions')) return jsonResponse([])
      return jsonResponse({})
    }),
  )
})

afterEach(() => {
  useSearchState.getState().clear()
  useSearchBasket.getState().reset()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('FIX-251 页面级 window 监听 mount/unmount 净增量为零', () => {
  it('SearchPage 反复进出 3 轮：每个事件类型 add 数 === remove 数', () => {
    const counts = spyWindowListeners()

    for (let cycle = 0; cycle < 3; cycle += 1) {
      const { unmount } = render(withProviders(<SearchPage />))
      unmount()
    }

    expect(counts.size).toBeGreaterThan(0) // 页面确实注册过 window 监听
    for (const [type, { added, removed }] of counts) {
      expect(removed, `事件 "${type}" 泄漏 ${added - removed} 个监听`).toBe(added)
    }
  })

  it('LoginScreen 反复进出 3 轮：online 监听不随进出累积', () => {
    const counts = spyWindowListeners()

    for (let cycle = 0; cycle < 3; cycle += 1) {
      const { unmount } = render(withProviders(<LoginScreen />))
      unmount()
    }

    // LoginScreen 自身 + TanStack OnlineManager（单例）都会注册 online；
    // 契约是不随 mount/unmount 累积——每类监听 add 数 === remove 数。
    const online = counts.get('online')
    expect(online).toBeDefined()
    expect(online!.added).toBeGreaterThanOrEqual(3)
    expect(online!.removed).toBe(online!.added)
    for (const [type, { added, removed }] of counts) {
      expect(removed, `事件 "${type}" 泄漏 ${added - removed} 个监听`).toBe(added)
    }
  })
})
