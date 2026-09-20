/** 键盘快捷键 — 0010 Gate B。
 *
 * 基础集（Spec §设计规格 + pool #06 补齐）：
 *   j / ↓ 下一篇   k / ↑ 上一篇   u 切换未读视图
 *   s     收藏切换（当前选中文章，走既有 mutation）
 *   /     跳转搜索并聚焦输入框
 *   ?     快捷键帮助弹窗（App 渲染 ShortcutsHelpDialog）
 *   Escape 关闭浮层（Modal/Drawer 已有自己的监听，这里不重复处理）
 *
 * 纪律（硬边界 10）：
 * - 输入框/下拉等可编辑元素聚焦时一律不触发（isEditable 判断）；
 * - 有修饰键（Ctrl/Meta/Alt）的组合键不拦截；
 * - 键盘事件挂在 window（列表没有天然的聚焦容器），依赖 reader-ui
 *   store 的当前选择做导航——不需要 DOM 滚动定位（列表本身可滚动，
 *   键盘导航只改选择，视觉滚动交给浏览器自然行为 + scrollIntoView）。 */

import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useReaderUi } from '../store/reader-ui'
import { scopeKey, type ContentScope } from './navigation'
import { useEntryStateMutation } from '../api/queries'
import { effectiveBinding, formatCombo, loadCustomShortcuts } from './custom-shortcuts'

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

/** F30：命令面板开关事件。keyboard-shortcuts 只派发事件，CommandPalette
 * 挂载后监听并自持开关状态（解耦：快捷键模块不感知面板实现）。 */
export const COMMAND_PALETTE_TOGGLE_EVENT = 'lumirss-command-palette-toggle'

/** 快捷键动作注册表（单一真源）：actionId → 默认组合 + 展示文案。
 * F037：帮助弹窗 / 设置页 / 实际按键匹配都从这里派生；用户覆盖
 * （lib/custom-shortcuts）经 effectiveBinding 优先于默认组合。 */
export interface ShortcutActionDef {
  id: string
  keys: string
  action: string
}

export const SHORTCUT_ACTIONS: ShortcutActionDef[] = [
  { id: 'next', keys: 'j / ↓', action: '下一篇' },
  { id: 'prev', keys: 'k / ↑', action: '上一篇' },
  { id: 'toggleUnread', keys: 'u', action: '切换未读视图' },
  { id: 'toggleStar', keys: 's', action: '收藏 / 取消收藏当前文章' },
  { id: 'search', keys: '/', action: '跳转搜索' },
  { id: 'help', keys: '?', action: '快捷键帮助' },
  { id: 'commandPalette', keys: 'Ctrl / ⌘ K', action: '命令面板' },
  { id: 'closeOverlay', keys: 'Escape', action: '关闭弹窗 / 抽屉' },
]

/** 默认绑定（combo 归一化 token；'j / ↓' 双绑定以主键为覆盖目标）。 */
export const DEFAULT_BINDINGS: Record<string, string> = {
  next: 'j',
  prev: 'k',
  toggleUnread: 'u',
  toggleStar: 's',
  search: '/',
  help: '?',
  commandPalette: 'mod+k',
  closeOverlay: 'escape',
}

/** 快捷键速查表数据（设置中心「快捷键」页与「?」帮助弹窗只读展示同一份）。
 * F037：传入用户覆盖时返回生效绑定（覆盖项 keys 替换 + overridden 标记）。 */
export function effectiveShortcuts(custom: Record<string, string> = {}): (ShortcutActionDef & { overridden: boolean })[] {
  return SHORTCUT_ACTIONS.map((def) => {
    const override = custom[def.id]
    if (typeof override === 'string' && override !== '') {
      return { ...def, keys: formatCombo(override), overridden: true }
    }
    return { ...def, overridden: false }
  })
}

/** 兼容旧消费方（静态展示）；新代码请用 effectiveShortcuts。 */
export const SHORTCUTS: { keys: string; action: string }[] = SHORTCUT_ACTIONS.map(
  ({ keys, action }) => ({ keys, action }),
)

export interface ShortcutOptions {
  /** 「?」按下时回调（App 挂帮助弹窗；不传则该键不生效）。 */
  onShowShortcutsHelp?: () => void
}

/** F037：把 KeyboardEvent 折叠成与绑定表同构的 combo token。
 * e.key 已是移位后的字符（如 '?'、'/'），单字符非字母时不再叠加 shift。 */
function pressedCombo(e: KeyboardEvent): string {
  const mods: string[] = []
  if (e.ctrlKey || e.metaKey) mods.push('mod')
  if (e.altKey) mods.push('alt')
  const key = e.key.toLowerCase()
  if (e.shiftKey && !(key.length === 1 && !/[a-z0-9]/i.test(key))) mods.push('shift')
  const ARROWS: Record<string, string> = {
    arrowup: 'up',
    arrowdown: 'down',
    arrowleft: 'left',
    arrowright: 'right',
  }
  const token = ARROWS[key] ?? key
  return [...mods, token].join('+')
}

export function useKeyboardShortcuts(options: ShortcutOptions = {}): void {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const selectView = useReaderUi((s) => s.selectView)
  const selectSection = useReaderUi((s) => s.selectSection)
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()
  const helpCallbackRef = useRef(options.onShowShortcutsHelp)
  helpCallbackRef.current = options.onShowShortcutsHelp

  useEffect(() => {
    // F037：用户覆盖优先于默认（每次 effect 重读 localStorage 覆盖表）
    const custom = loadCustomShortcuts()
    const bind = (id: string) => effectiveBinding(id, DEFAULT_BINDINGS, custom)
    const onKeyDown = (e: KeyboardEvent) => {
      const pressed = pressedCombo(e)
      // F30：Ctrl/⌘+K 唤起/关闭命令面板（toggle，可用 mod+k 覆盖）。既有纪律
      // 保持：输入框聚焦时不劫持——命令面板自身输入框的 Ctrl+K 关闭由面板
      // 内部处理；也不受 isModalOpen 门控（面板本身是浮层，toggle 语义自洽）。
      if (pressed === bind('commandPalette')) {
        if (isEditable(e.target)) return
        e.preventDefault()
        window.dispatchEvent(new CustomEvent(COMMAND_PALETTE_TOGGLE_EVENT))
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditable(e.target)) return
      // AUDIT-014：当真实模态（aria-modal）打开时，j/k/u/s 不得改动其
      // 下方隐藏的 Reader/timeline。Escape/Tab/焦点陷阱由各 Dialog 原语
      // 自行处理，本处理器只抑制全局导航/收藏键。
      if (isModalOpen()) return

      const state = useReaderUi.getState()
      // j/k 的方向键副绑定（默认表展示 'j / ↓'；覆盖主键后副键仍可用）
      const matchWithAlias = (id: string, alias: string) =>
        pressed === bind(id) || (bind(id) !== alias && pressed === alias)

      // 「?」= Shift+/（e.key 即 '?'）：任何页面唤起帮助。
      if (matchWithAlias('help', '?')) {
        e.preventDefault()
        helpCallbackRef.current?.()
        return
      }
      // 「/」= 跳转搜索：不在搜索页则先切 section，再聚焦输入框。
      if (pressed === bind('search')) {
        e.preventDefault()
        if (state.section !== 'search') selectSection('search')
        requestAnimationFrame(() => {
          document
            .querySelector<HTMLInputElement>(
              '[data-shortcut-target="search-input"]',
            )
            ?.focus()
        })
        return
      }
      if (matchWithAlias('next', 'down')) {
        e.preventDefault()
        const next = findSiblingEntry(queryClient, state, +1)
        if (next !== null) {
          selectEntry(next)
          scrollEntryIntoView(next)
        }
        return
      }
      if (matchWithAlias('prev', 'up')) {
        e.preventDefault()
        const prev = findSiblingEntry(queryClient, state, -1)
        if (prev !== null) {
          selectEntry(prev)
          scrollEntryIntoView(prev)
        }
        return
      }
      if (pressed === bind('toggleUnread')) {
        e.preventDefault()
        // 在 all ↔ unread 间切换（其它视图先回到 all，再切 unread）
        selectView(state.view === 'unread' ? 'all' : 'unread')
        return
      }
      if (pressed === bind('toggleStar')) {
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
  }, [selectEntry, selectView, selectSection, mutation, queryClient])
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
