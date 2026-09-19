/** F08 卡片滑动 — 纯逻辑边界 + EntryCard 触摸接线。
 *
 * 纯函数（lib/card-swipe）：
 * - 起点左缘 24px 内不激活（让给侧滑返回）；
 * - 预览位移 dx×0.4 上限 ±100；
 * - 纵向让出 |dy|>|dx|；
 * - 提交阈值 |dx|≥80 且非纵向。
 *
 * 组件（EntryCard）：
 * - settings.cardSwipeAction 驱动：read → PATCH /state body {"read":true}；
 *   star → {"starred":true}；readLater → POST workspaces/read-later/items；
 * - 未达阈值回弹（无 mutation）；纵向让出；边缘起点不处理；
 * - 'none' 时不接手势（无动作层）。
 */

import { act, fireEvent, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import EntryCard from '../components/EntryCard'
import {
  CARD_SWIPE_COMMIT_PX,
  CARD_SWIPE_EDGE_EXCLUDE_PX,
  CARD_SWIPE_PREVIEW_MAX_PX,
  swipeIsVertical,
  swipePreviewOffset,
  swipePreviewOpacity,
  swipeShouldCommit,
  swipeStartAllowed,
} from '../lib/card-swipe'
import { useAppSettings } from '../store/app-settings'
import type { EntryListItem } from '../api/types'

function item(overrides: Partial<EntryListItem> = {}): EntryListItem {
  return {
    entryRef: 'e1.a',
    title: '文章标题',
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T08:00:00Z',
    read: false,
    starred: false,
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>
}

afterEach(() => {
  useAppSettings.getState().update({ cardSwipeAction: 'none' })
  vi.unstubAllGlobals()
})

describe('card-swipe 纯函数边界', () => {
  it('swipeStartAllowed：屏幕左缘 24px 内不激活（让给侧滑返回）', () => {
    expect(CARD_SWIPE_EDGE_EXCLUDE_PX).toBe(24)
    expect(swipeStartAllowed(0)).toBe(false)
    expect(swipeStartAllowed(10)).toBe(false)
    expect(swipeStartAllowed(24)).toBe(false)
    expect(swipeStartAllowed(25)).toBe(true)
    expect(swipeStartAllowed(200)).toBe(true)
  })

  it('swipePreviewOffset：dx×0.4，钳制 ±100', () => {
    expect(CARD_SWIPE_PREVIEW_MAX_PX).toBe(100)
    expect(swipePreviewOffset(0)).toBe(0)
    expect(swipePreviewOffset(100)).toBe(40)
    expect(swipePreviewOffset(-100)).toBe(-40)
    expect(swipePreviewOffset(250)).toBe(100) // 250×0.4=100 恰在上限
    expect(swipePreviewOffset(400)).toBe(100) // 超出钳制
    expect(swipePreviewOffset(-400)).toBe(-100)
  })

  it('swipeIsVertical / swipeShouldCommit：纵向让出 + 80px 提交阈值', () => {
    expect(CARD_SWIPE_COMMIT_PX).toBe(80)
    expect(swipeIsVertical(30, 50)).toBe(true)
    expect(swipeIsVertical(50, 30)).toBe(false)
    expect(swipeIsVertical(50, 50)).toBe(false)
    // 达阈值：非纵向 |dx|>=80（双向）
    expect(swipeShouldCommit(80, 0)).toBe(true)
    expect(swipeShouldCommit(160, 10)).toBe(true)
    expect(swipeShouldCommit(-80, 0)).toBe(true)
    // 未达阈值
    expect(swipeShouldCommit(79, 0)).toBe(false)
    expect(swipeShouldCommit(0, 0)).toBe(false)
    // 纵向让出（位移够大也不提交）
    expect(swipeShouldCommit(100, 120)).toBe(false)
  })

  it('swipePreviewOpacity：80px 处全显，钳制 0–1', () => {
    expect(swipePreviewOpacity(0)).toBe(0)
    expect(swipePreviewOpacity(40)).toBe(0.5)
    expect(swipePreviewOpacity(80)).toBe(1)
    expect(swipePreviewOpacity(160)).toBe(1)
  })
})

describe('EntryCard 触摸接线（F08）', () => {
  it('cardSwipeAction=read：达阈值 touchend 发出 PATCH body {"read":true}；未达回弹不发', async () => {
    const patchCalls: { url: string; body: unknown }[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/state') && init?.method === 'PATCH') {
        patchCalls.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ cardSwipeAction: 'read' })
    render(withProviders(<EntryCard item={item()} selected={false} />))
    const card = document.querySelector('[data-entry-ref="e1.a"]') as HTMLElement

    // 未达阈值（dx=60 → 预览 24）→ 回弹，无 mutation
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 160, clientY: 100 }] })
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 160, clientY: 100 }] })
    expect(patchCalls).toHaveLength(0)

    // 达阈值（dx=200 ≥ 80，非纵向）→ 提交 read
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 300, clientY: 105 }] })
    // 跟手预览：动作背景层出现并标注 read
    expect(document.querySelector('[data-swipe-action-hint="read"]')).not.toBeNull()
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 300, clientY: 105 }] })
    await waitFor(() => expect(patchCalls).toHaveLength(1))
    expect(patchCalls[0]!.body).toEqual({ read: true })
    expect(patchCalls[0]!.url).toContain('/api/v1/entries/e1.a/state')
    // 动作后卡片回位（预览层消失）
    expect(document.querySelector('[data-swipe-action-hint]')).toBeNull()
  })

  it('cardSwipeAction=star：提交后 PATCH body {"starred":true}（未收藏 → 收藏）', async () => {
    const patchCalls: { url: string; body: unknown }[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/state') && init?.method === 'PATCH') {
        patchCalls.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ cardSwipeAction: 'star' })
    render(withProviders(<EntryCard item={item()} selected={false} />))
    const card = document.querySelector('[data-entry-ref="e1.a"]') as HTMLElement
    fireEvent.touchStart(card, { touches: [{ clientX: 50, clientY: 50 }] })
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 160, clientY: 50 }] })
    await waitFor(() => expect(patchCalls).toHaveLength(1))
    expect(patchCalls[0]!.body).toEqual({ starred: true })
  })

  it('cardSwipeAction=readLater：提交后 POST workspaces/read-later/items（itemRef 带 rss: 前缀）', async () => {
    const postCalls: { url: string; body: unknown }[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/workspaces/read-later/items') && init?.method === 'POST') {
        postCalls.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(jsonResponse({}))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ cardSwipeAction: 'readLater' })
    render(withProviders(<EntryCard item={item()} selected={false} />))
    const card = document.querySelector('[data-entry-ref="e1.a"]') as HTMLElement
    fireEvent.touchStart(card, { touches: [{ clientX: 50, clientY: 50 }] })
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 200, clientY: 50 }] })
    await waitFor(() => expect(postCalls).toHaveLength(1))
    expect(postCalls[0]!.body).toEqual({ itemRef: 'rss:e1.a' })
  })

  it('纵向让出与左缘起点：不预览、不提交', async () => {
    const patchCalls: unknown[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/state') && init?.method === 'PATCH') {
        patchCalls.push(String(init.body))
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ cardSwipeAction: 'read' })
    render(withProviders(<EntryCard item={item()} selected={false} />))
    const card = document.querySelector('[data-entry-ref="e1.a"]') as HTMLElement

    // 纵向让出：dy > dx，即使 |dx| ≥ 80 也不提交
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 220, clientY: 320 }] })
    expect(document.querySelector('[data-swipe-action-hint]')).toBeNull()
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 220, clientY: 320 }] })

    // 左缘起点（clientX=10 ≤ 24）整段手势不处理
    fireEvent.touchStart(card, { touches: [{ clientX: 10, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 300, clientY: 100 }] })
    expect(document.querySelector('[data-swipe-action-hint]')).toBeNull()
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 300, clientY: 100 }] })

    // 留一拍确认没有 PATCH 发出
    await act(async () => {
      await Promise.resolve()
    })
    expect(patchCalls).toHaveLength(0)
  })

  it("cardSwipeAction='none'：不接手势（滑动无动作层、无 mutation）", async () => {
    const patchCalls: unknown[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/state') && init?.method === 'PATCH') {
        patchCalls.push(String(init.body))
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({ items: [] }))
    })
    vi.stubGlobal('fetch', fetchMock)
    useAppSettings.getState().update({ cardSwipeAction: 'none' })
    render(withProviders(<EntryCard item={item()} selected={false} />))
    const card = document.querySelector('[data-entry-ref="e1.a"]') as HTMLElement
    expect(card.getAttribute('data-swipe-action-hint')).toBeNull()
    fireEvent.touchStart(card, { touches: [{ clientX: 100, clientY: 100 }] })
    fireEvent.touchMove(card, { touches: [{ clientX: 400, clientY: 100 }] })
    expect(document.querySelector('[data-swipe-action-hint]')).toBeNull()
    fireEvent.touchEnd(card, { changedTouches: [{ clientX: 400, clientY: 100 }] })
    await act(async () => {
      await Promise.resolve()
    })
    expect(patchCalls).toHaveLength(0)
  })
})
