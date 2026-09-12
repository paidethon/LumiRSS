/** read-later 集成层 — P0-01 服务端时间线版。
 *
 * UiView：前端视图语义（EntryView + read-later workspace）。read-later
 * 的真源自 phase2 recovery 起是 BFF 保留工作区 `read-later` 的**服务端
 * 时间线**（GET /workspaces/read-later/timeline：server-driven、cursor
 * 分页、悬挂成员 stale 行可见；ADR 0004：服务端是唯一事实）。
 *
 * 相对旧实现的三点收窄：
 * - 不再把 read-later 映射成 view=all 拉全量后本地过滤（未翻到的页
 *   不可见是对用户的谎言）——列表直接消费 useReadLaterTimeline；
 * - 不再有 localStorage 双写与一次性 syncedRef 对账——Clock 按钮激活态
 *   来自 useReadLaterRefs（服务端成员清单）+ 在途 mutation 的乐观覆盖
 *   （未落库前不假装完成，失败原样回滚，镜像 useLibraryFavoriteToggle）；
 * - toggle 走 useReadLaterMemberMutation：时间线乐观移除 + 失败回滚 +
 *   ['workspace','read-later'] 前缀失效。 */

import { useMemo } from 'react'
import {
  useReadLaterMemberMutation,
  useReadLaterRefs,
} from '../api/queries'

/** 前端视图全集（含 read-later workspace） */
export type UiView = 'all' | 'unread' | 'starred' | 'read-later'

/** 服务端保留工作区 id（migration 0008 种子行）。 */
export const READ_LATER_WORKSPACE_ID = 'read-later'

/** 稍后读切换（列表行 / 阅读页头部 / 卡片三入口共享）。
 * 激活态语义（诚实）：
 * - 真值 = 服务端成员清单命中；
 * - 本人条目有在途 mutation 时以其目标值为准（乐观，未落库不假装完成）；
 * - pending / error 只在本人条目上；error 原样透出（调用方渲染，
 *   不吞不假装成功——移除失败时行保留，加入失败时按钮回弹）。 */
export function useToggleReadLater(): {
  isReadLater: (entryRef: string) => boolean
  toggleReadLater: (entryRef: string) => void
  pendingFor: (entryRef: string) => boolean
  errorFor: (entryRef: string) => Error | null
} {
  const refsQuery = useReadLaterRefs()
  const mutation = useReadLaterMemberMutation()

  const serverRefs = useMemo(
    () =>
      new Set(
        (refsQuery.data?.items ?? [])
          .filter((it) => it.itemRef.startsWith('rss:'))
          .map((it) => it.itemRef.slice('rss:'.length)),
      ),
    [refsQuery.data],
  )

  const activeEntryRef = mutation.variables?.entryRef ?? null

  const membershipOf = (entryRef: string): boolean => {
    if (entryRef === activeEntryRef) {
      // 在途/刚结束的本人操作优先：乐观展示目标值，失败由 errorFor 透出。
      return mutation.variables!.add
    }
    return serverRefs.has(entryRef)
  }

  return {
    isReadLater: membershipOf,
    toggleReadLater: (entryRef) => {
      mutation.mutate({ entryRef, add: !membershipOf(entryRef) })
    },
    pendingFor: (entryRef) => entryRef === activeEntryRef && mutation.isPending,
    errorFor: (entryRef) =>
      entryRef === activeEntryRef && mutation.isError ? mutation.error : null,
  }
}
