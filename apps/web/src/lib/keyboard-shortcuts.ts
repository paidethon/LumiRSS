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
import { scopeKey, type ContentScope } from './navigation'
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

/** AUDIT-014：是否存在打开的真实模态（Dialog/Sheet/Drawer）。
 * 仓库内所有模态原语都携 aria-modal="true"，因此这是可靠的信号。 */
function isModalOpen(): boolean {
  return document.querySelector('[aria-modal="true"]') !== null
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
      // AUDIT-014：当真实模态（aria-modal）打开时，j/k/u/s 不得改动其
      // 下方隐藏的 Reader/timeline。Escape/Tab/焦点陷阱由各 Dialog 原语
      // 自行处理，本处理器只抑制全局导航/收藏键。
      if (isModalOpen()) return

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
  state: { view: string; scope: unknown; selectedEntryRef: string | null },
  direction: 1 | -1,
): string | null {
  const entries = collectEntries(queryClient, state.view, scopeKey(state.scope as ContentScope))
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
  // 0011：scope key 形状与 queries.ts 一致（'all'|'rss'|{categoryId}|{feedUrl}）
  // 扫描全部已缓存 scope（j/k 导航在当前 scope 内找兄弟；findEntry 容错全扫）
  for (const key of entriesKeysInCache(queryClient)) {
    const entries = collectEntries(queryClient, key.view, key.scope as ReturnType<typeof scopeKey>)
    const hit = entries.find((e) => e.entryRef === entryRef)
    if (hit) return hit
  }
  return null
}

type CacheEntry = { entryRef: string; starred: boolean }

function collectEntries(
  queryClient: ReturnType<typeof useQueryClient>,
  view: string,
  scope: ReturnType<typeof scopeKey>,
): CacheEntry[] {
  // key 构造与 queries.ts useEntries 完全一致：{ view, scope: scopeKey(scope) }（§19）
  const key = ['entries', { view, scope }]
  const data = queryClient.getQueryData<{ pages?: { items?: CacheEntry[] }[] }>(key as never)
  const pages = data?.pages ?? []
  return pages.flatMap((p) => p.items ?? [])
}

/** 枚举 cache 中全部 entries key 的 (view, scope) 对（findEntry 容错扫描）。 */
function entriesKeysInCache(
  queryClient: ReturnType<typeof useQueryClient>,
): { view: string; scope: unknown }[] {
  return queryClient
    .getQueryCache()
    .getAll()
    .filter((q) => q.queryKey[0] === 'entries')
    .map((q) => {
      const params = (q.queryKey[1] ?? {}) as { view?: string; scope?: unknown }
      return { view: String(params.view ?? 'all'), scope: params.scope ?? 'all' } as { view: string; scope: ReturnType<typeof scopeKey> }
    })
}

function scrollEntryIntoView(entryRef: string): void {
  // EntryRow / EntryCard 的根元素（div）带 data-entry-ref；AUDIT-013：
  // 之前用 button[data-entry-ref] 选择器（不存在该嵌套）导致 j/k
  // 从不滚动。直接选中携带该属性的真实元素；rAF 等待 React 提交选中态。
  requestAnimationFrame(() => {
    const el = document.querySelector(`[data-entry-ref="${CSS.escape(entryRef)}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  })
}
