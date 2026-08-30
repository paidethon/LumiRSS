/** read-later 集成层 — 0011 修正补充。
 *
 * UiView：前端视图语义（EntryView + read-later workspace）。
 * read-later 不是 BFF 契约（§36/§37 最小接口原则：FreshRSS 无此
 * marker）——API 请求层把 read-later 翻译为 view=all 拉全量，列表
 * 侧对已加载页做客户端过滤（§26：加入不移除；移除立即从列表消失）。
 *
 * useToggleReadLater：共享 mutation 语义 hook（§24/§38）——EntryRow /
 * EntryCard / ReaderHeader 三个入口走同一 store，零网络请求（本地
 * marker），点击即时切换（天然乐观，无需 rollback 框架）。 */

import { useReadLater } from '../store/read-later'
import type { EntryView } from '../api/types'

/** 前端视图全集（含 read-later workspace） */
export type UiView = EntryView | 'read-later'

/** read-later 视图在 API 层的翻译：全量拉取（客户端过滤）。 */
export function toApiView(view: UiView): EntryView {
  return view === 'read-later' ? 'all' : view
}

export function useToggleReadLater(): {
  isReadLater: (entryRef: string) => boolean
  toggleReadLater: (entryRef: string) => void
} {
  const items = useReadLater((s) => s.items)
  const toggle = useReadLater((s) => s.toggleReadLater)
  const refs = new Set(items.map((it) => it.entryRef))
  return {
    isReadLater: (entryRef) => refs.has(entryRef),
    toggleReadLater: (entryRef) => {
      toggle(entryRef)
    },
  }
}
