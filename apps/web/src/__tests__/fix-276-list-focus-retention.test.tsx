/**
 * FIX-276 — 列表焦点项不会被「虚拟化回收」弄丢（BASELINE_OK 守卫）。
 *
 * 前提核实：LumiRSS 文章列表**没有虚拟化窗口**——EntryList/ReadLaterList
 * 把全部已加载行渲染进同一个 `<ul>`（key=entryRef 稳定），视口外行只
 * 用 CSS `lumi-row-cv`（content-visibility）跳过 layout/paint，DOM 节点
 * 永不回收。因此「焦点项被回收后焦点消失」的前提不成立：
 * - 兄弟行数据更新（如另一行被标记已读）时，焦点行的 DOM 节点被 React
 *   按 key 复用，焦点保持在原节点上、仍然可操作；
 * - 本守卫钉定该行为，防止未来引入窗口化虚拟列表时无声破坏它。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import EntryRow from '../components/EntryRow'
import type { EntryListItem } from '../api/types'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import { useReaderUi } from '../store/reader-ui'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function item(ref: string, read_: boolean): EntryListItem {
  return {
    entryRef: ref,
    title: `文章 ${ref}`,
    feedTitle: '示例源 A',
    author: null,
    url: null,
    publishedAt: '2026-08-28T00:00:00Z',
    read: read_,
    starred: false,
  } as EntryListItem
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, cardSwipeAction: 'none' } })
  useReaderUi.setState({ selectedEntryRef: null })
  vi.stubGlobal('fetch', vi.fn(() => new Response('{}', { status: 200 })))
})

describe('FIX-276: 列表无虚拟化，焦点行跨数据更新存活', () => {
  it('守卫前提：EntryList 全量渲染（content-visibility 保留 DOM），无窗口化依赖', () => {
    const list = read('components/EntryList.tsx')
    // 视口外行保留 DOM：content-visibility 行类存在（滚动恢复/焦点不受影响）
    expect(list).toContain('lumi-row-cv')
    // 无任何虚拟化窗口库（rows.map 全量渲染）
    expect(list).not.toMatch(/react-window|react-virtual|@tanstack\/react-virtual|virtua/)
  })

  it('兄弟行更新（标记已读）后，焦点行的同一 DOM 节点保持聚焦且可操作', () => {
    const view = render(
      withProviders(
        <ul>
          <li>
            <EntryRow item={item('a', false)} selected={false} />
          </li>
          <li>
            <EntryRow item={item('b', false)} selected={false} />
          </li>
          <li>
            <EntryRow item={item('c', false)} selected={false} />
          </li>
        </ul>,
      ),
    )

    // 聚焦第二行标题按钮（键盘用户当前位置；title=文章标题是标题钮特有）
    const rowB = view.container.querySelector('[data-entry-ref="b"]') as HTMLElement
    const titleB = rowB.querySelector('button[title="文章 b"]') as HTMLButtonElement
    titleB.focus()
    expect(document.activeElement).toBe(titleB)

    // 第一行被标记已读（列表数据更新，焦点行自身 props 未变）
    view.rerender(
      withProviders(
        <ul>
          <li>
            <EntryRow item={item('a', true)} selected={false} />
          </li>
          <li>
            <EntryRow item={item('b', false)} selected={false} />
          </li>
          <li>
            <EntryRow item={item('c', false)} selected={false} />
          </li>
        </ul>,
      ),
    )

    // 同一 DOM 节点仍在文档中且保持焦点（没有被回收重建）
    expect(document.activeElement).toBe(titleB)
    expect(titleB.isConnected).toBe(true)
    // 焦点项仍可操作：Enter 打开该文章（selectEntry 命中 b）
    fireEvent.click(titleB)
    expect(useReaderUi.getState().selectedEntryRef).toBe('b')
  })
})
