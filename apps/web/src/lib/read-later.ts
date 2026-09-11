/** read-later 集成层 — 0011 修正补充；phase2 M1 升级为服务端工作区。
 *
 * UiView：前端视图语义（EntryView + read-later workspace）。
 * read-later 的真源自 phase2 M1 起是 BFF 保留工作区
 * `read-later`（workspace_items 只存 rss:<entryRef>）；本地
 * localStorage 集合降级为**缓存**：时间线 read-later 视图继续对已
 * 加载页做客户端过滤（§26：加入不移除；移除立即消失），保证离线
 * 可用与零闪烁；toggle 双写（本地即时 + 服务端 mutation）。
 *
 * useReadLaterServerSync：挂载一次。首次成功拉取时（a）把 localStorage
 * 遗留条目一次性迁移到服务端（幂等：服务端按 (workspace,ref) 去重），
 * （b）之后以服务端列表对账本地缓存。mutation 在途时跳过对账，
 * 避免覆盖乐观更新；失败静默保留本地缓存（离线优先语义）。 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import {
  addWorkspaceItem,
  listWorkspaceItems,
  removeWorkspaceItem,
} from '../api/client'
import {
  beginReadLaterMutation,
  endReadLaterMutation,
  hasInFlightReadLaterMutation,
  isServerMigrated,
  markServerMigrated,
  useReadLater,
} from '../store/read-later'
import type { EntryView } from '../api/types'

/** 前端视图全集（含 read-later workspace） */
export type UiView = EntryView | 'read-later'

/** 服务端保留工作区 id（migration 0008 种子行）。 */
export const READ_LATER_WORKSPACE_ID = 'read-later'

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
      const adding = toggle(entryRef)
      beginReadLaterMutation()
      const request = adding
        ? addWorkspaceItem(READ_LATER_WORKSPACE_ID, `rss:${entryRef}`)
        : removeWorkspaceItem(READ_LATER_WORKSPACE_ID, `rss:${entryRef}`)
      request.finally(endReadLaterMutation).catch(() => {
        // 服务端写失败：本地缓存保留（离线优先）；下次 hydration 对账。
      })
    },
  }
}

/** 本地缓存 ← 服务端 read-later 工作区的启动同步（含一次性迁移）。 */
export function useReadLaterServerSync(): void {
  const queryClient = useQueryClient()
  const items = useReadLater((s) => s.items)
  const hydrate = useReadLater((s) => s.hydrate)
  // 只在首次挂载时迁移/对账一次；后续以乐观双写维护一致性。
  const syncedRef = useRef(false)

  const query = useQuery({
    queryKey: ['workspace', READ_LATER_WORKSPACE_ID, 'items'],
    queryFn: ({ signal }) => listWorkspaceItems(READ_LATER_WORKSPACE_ID, signal),
    staleTime: 30_000,
  })

  useEffect(() => {
    if (query.isSuccess && !syncedRef.current) {
      syncedRef.current = true
      const serverRefs = new Set(
        query.data.items
          .filter((it) => it.itemRef.startsWith('rss:'))
          .map((it) => it.itemRef.slice(4)),
      )
      const localRefs = new Set(items.map((it) => it.entryRef))

      // (a) 一次性迁移：localStorage 遗留 → 服务端（幂等 add）。
      if (!isServerMigrated() && items.length > 0) {
        const missing = items.filter((it) => !serverRefs.has(it.entryRef))
        beginReadLaterMutation()
        Promise.allSettled(
          missing.map((it) =>
            addWorkspaceItem(READ_LATER_WORKSPACE_ID, `rss:${it.entryRef}`),
          ),
        )
          .then((results) => {
            results.forEach((r) => {
              if (r.status === 'fulfilled') serverRefs.add(r.value.itemRef.slice(4))
            })
            markServerMigrated()
            void queryClient.invalidateQueries({
              queryKey: ['workspace', READ_LATER_WORKSPACE_ID, 'items'],
            })
          })
          .finally(endReadLaterMutation)
        return
      }

      // (b) 对账：以服务端为真源替换本地缓存（mutation 在途时跳过）。
      if (!hasInFlightReadLaterMutation()) {
        const now = Date.now()
        const serverItems = query.data.items
          .filter((it) => it.itemRef.startsWith('rss:'))
          .map((it) => ({ entryRef: it.itemRef.slice(4), addedAt: now }))
        if (
          serverItems.length !== items.length ||
          serverItems.some((it) => !localRefs.has(it.entryRef))
        ) {
          hydrate(serverItems)
        }
      }
    }
  }, [query.isSuccess, query.data, items, hydrate, queryClient])
}
