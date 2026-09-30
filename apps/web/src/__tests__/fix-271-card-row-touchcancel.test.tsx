/**
 * FIX-271（列表行半边）— EntryCard / EntryRow 滑动手势的 touchcancel 归位。
 *
 * 修复前：卡片滑动手势只处理 touchstart/move/end——touchcancel（来电、
 * 系统手势、浏览器接管触摸）后 swipeDx 卡在非零值：行停留在 translateX
 * 预览位、动作背景层持续露出，直到下一次 touchstart 才复位。
 * 修复后：onTouchCancel 立即清 tracking 并归零预览；绝不提交动作。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EntryCard from '../components/EntryCard'
import EntryRow from '../components/EntryRow'
import type { EntryListItem } from '../api/types'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

function item(ref: string): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: false,
    starred: false,
  } as EntryListItem
}

function renderRow(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

/** 滑动到预览位（未达提交阈值：位移 40px < 80px，touchend 会回弹）。 */
function dragToPreview(row: HTMLElement) {
  fireEvent.touchStart(row, { touches: [{ clientX: 160, clientY: 100 }] })
  fireEvent.touchMove(row, { touches: [{ clientX: 200, clientY: 100 }] })
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({
    settings: { ...DEFAULT_APP_SETTINGS, cardSwipeAction: 'read' },
  })
  useReaderUi.setState({ selectedEntryRef: null })
  vi.stubGlobal('fetch', vi.fn(() => new Response('{}', { status: 200 })))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe.each([
  { name: 'EntryCard', Component: EntryCard },
  { name: 'EntryRow', Component: EntryRow },
])('$name touchcancel 归位', ({ Component }) => {
  it('touchcancel 立即撤下动作背景层与 translateX 预览', () => {
    const view = renderRow(<Component item={item('e1.a')} selected={false} />)
    const row = view.container.querySelector('[data-entry-ref="e1.a"]') as HTMLElement
    dragToPreview(row)
    // 预览中：动作背景层可见（swipeDx !== 0）
    expect(row.querySelector('[data-swipe-action-hint]')).not.toBeNull()

    fireEvent.touchCancel(row)
    // 归位：背景层卸载，内容层 transform 清空
    expect(row.querySelector('[data-swipe-action-hint]')).toBeNull()
    const transformed = row.querySelector<HTMLElement>('[style*="translateX"]')
    expect(transformed).toBeNull()
  })

  it('touchcancel 不提交滑动动作（未发已读 mutation）', () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL) => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const view = renderRow(<Component item={item('e2.a')} selected={false} />)
    const row = view.container.querySelector('[data-entry-ref="e2.a"]') as HTMLElement
    // 拖过提交阈值后直接被系统取消——取消语义不得当作 touchend 提交。
    fireEvent.touchStart(row, { touches: [{ clientX: 160, clientY: 100 }] })
    fireEvent.touchMove(row, { touches: [{ clientX: 260, clientY: 100 }] })
    fireEvent.touchCancel(row)
    expect(
      fetchMock.mock.calls.filter((call) => String(call[0]).includes('/state')),
    ).toHaveLength(0)
  })
})
