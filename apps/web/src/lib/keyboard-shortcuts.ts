/** 键盘快捷键 — 0010 Gate B。
 *
 * 基础集（Spec §设计规格）：
 *   j / ↓ 下一篇   k / ↑ 上一篇   u 切换未读视图
 *   s     收藏切换（当前选中文章，走既有 mutation）
 *   Escape 关闭浮层（Modal/Drawer 已有自己的监听，这里不重复处理）
 *
 * 纪律（硬边界 10）：
 * - 输入框/下拉等可编辑元素聚焦时一律不触发（isEditable 判断）；
 * - 有修饰键（Ctrl/Meta/Alt）的组合键不拦截；
 * - 键盘事件挂在 window（列表没有天然的聚焦容器），依赖 reader-ui
 *   store 的当前选择做导航——不需要 DOM 滚动定位（列表本身可滚动，
 *   键盘导航只改选择，视觉滚动交给浏览器自然行为 + scrollIntoView）。 */

import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useReaderUi } from '../store/reader-ui'
import { useEntryStateMutation } from '../api/queries'

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName.toLowerCase()
  return (
    tag === 'input' ||
    tag === 'textarea' ||
    tag === 'select' ||
    target.isContentEditable
  )
}

/** 快捷键速查表数据（设置中心「快捷键」页只读展示同一份）。 */
export const SHORTCUTS: { keys: string; action: string }[] = [
  { keys: 'j / ↓', action: '下一篇' },
  { keys: 'k / ↑', action: '上一篇' },
  { keys: 'u', action: '切换未读视图' },
  { keys: 's', action: '收藏 / 取消收藏当前文章' },
  { keys: 'Escape', action: '关闭弹窗 / 抽屉' },
]

export function useKeyboardShortcuts(): void {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const selectView = useReaderUi((s) => s.selectView)
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditable(e.target)) return

      const key = e.key.toLowerCase()
      const state = useReaderUi.getState()

      if (key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        const next = findSiblingEntry(queryClient, state, +1)
        if (next !== null) {
          selectEntry(next)
          scrollEntryIntoView(next)
        }
        return
      }
      if (key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        const prev = findSiblingEntry(queryClient, state, -1)
        if (prev !== null) {
          selectEntry(prev)
          scrollEntryIntoView(prev)
        }
        return
      }
      if (key === 'u') {
        e.preventDefault()
        // 在 all ↔ unread 间切换（其它视图先回到 all，再切 unread）
        selectView(state.view === 'unread' ? 'all' : 'unread')
        return
      }
      if (key === 's') {
        if (state.selectedEntryRef === null) return
        e.preventDefault()
        // 走既有 mutation：set 语义 + invalidation；starred 取当前缓存状态
        const entry = findEntry(queryClient, state.selectedEntryRef)
        if (entry !== null) {
          mutation.mutate({
            entryRef: entry.entryRef,
            patch: { starred: !entry.starred },
          })
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectEntry, selectView, mutation, queryClient])
}

/** 从当前缓存页里找选中项的相邻项（±1）。列表数据只在 Query cache，
 * 不复制进快捷键模块——与 ReaderPlaceholder 同一取数模式。 */
function findSiblingEntry(
  queryClient: ReturnType<typeof useQueryClient>,
  state: { view: string; selectedFeedUrl: string | null; selectedEntryRef: string | null },
  direction: 1 | -1,
): string | null {
  const entries = collectEntries(queryClient, state.view, state.selectedFeedUrl)
  if (entries.length === 0) return null
  if (state.selectedEntryRef === null) {
    return direction === 1 ? entries[0]!.entryRef : entries[entries.length - 1]!.entryRef
  }
  const idx = entries.findIndex((e) => e.entryRef === state.selectedEntryRef)
  if (idx === -1) return entries[0]!.entryRef
  const nextIdx = idx + direction
  if (nextIdx < 0 || nextIdx >= entries.length) return entries[idx]!.entryRef
  return entries[nextIdx]!.entryRef
}

function findEntry(
  queryClient: ReturnType<typeof useQueryClient>,
  entryRef: string,
): { entryRef: string; starred: boolean } | null {
  for (const view of ['all', 'unread', 'starred']) {
    const entries = collectEntries(queryClient, view, null)
    const hit = entries.find((e) => e.entryRef === entryRef)
    if (hit) return hit
    // feed 作用域的缓存
    for (const feed of feedKeysInCache(queryClient)) {
      const feedEntries = collectEntries(queryClient, view, feed)
      const feedHit = feedEntries.find((e) => e.entryRef === entryRef)
      if (feedHit) return feedHit
    }
  }
  return null
}

type CacheEntry = { entryRef: string; starred: boolean }

function collectEntries(
  queryClient: ReturnType<typeof useQueryClient>,
  view: string,
  feedUrl: string | null,
): CacheEntry[] {
  // key 构造与 queries.ts useEntries 完全一致：{ view, feedUrl }
  // （feedUrl 为 null 时也显式携带，保证 key 相等）
  const key = ['entries', { view, feedUrl }]
  const data = queryClient.getQueryData<{ pages?: { items?: CacheEntry[] }[] }>(key as never)
  const pages = data?.pages ?? []
  return pages.flatMap((p) => p.items ?? [])
}

function feedKeysInCache(queryClient: ReturnType<typeof useQueryClient>): string[] {
  // 从 feeds 缓存取全部 feedUrl（keys 结构稳定）
  const feeds = queryClient.getQueryData<{ feedUrl: string }[]>(['feeds'])
  return (feeds ?? []).map((f) => f.feedUrl)
}

function scrollEntryIntoView(entryRef: string): void {
  // EntryRow 根 button 带 data-entry-ref（EntryRow.tsx 同步添加）；
  // rAF 等待 React 提交选中态变化后再滚动。
  requestAnimationFrame(() => {
    const el = document.querySelector(`button[data-entry-ref="${CSS.escape(entryRef)}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  })
}
