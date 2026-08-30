/** TanStack Query hooks —— server state 的唯一入口。
 * useFeeds/useEntries 在 Sidebar / EntryList / ReaderPlaceholder 间共享
 * （同 query key 命中同一份 cache，不会重复请求）。 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getEntries, getEntry, getFeeds, setEntryState } from './client'
import type { UiView } from '../lib/read-later'
import { buildEntryQuery, scopeKey, type ContentScope } from '../lib/navigation'

export function useFeeds() {
  return useQuery({
    queryKey: ['feeds'],
    queryFn: ({ signal }) => getFeeds(signal),
  })
}

/** entries：NavigationTarget（scope + view）→ query（§18/§19 唯一映射）。
 * Query key 含 scope：不同 scope 不同 cache，切换不闪旧数据；cursor
 * 透传由 BFF scope envelope 保证不错乱。 */
export function useEntries(scope: ContentScope, view: UiView) {
  const entryQuery = buildEntryQuery(scope, view)
  return useInfiniteQuery({
    queryKey: ['entries', { view, scope: scopeKey(scope) }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      getEntries(
        {
          view: entryQuery.view,
          feedUrl: entryQuery.feedUrl,
          sourceType: entryQuery.sourceType,
          categoryId: entryQuery.categoryId,
          cursor: pageParam,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
}

/** 单篇 Detail。enabled：没有 selection（entryRef 为 null）时
 * 完全不发请求；切换 selection = 换 query key，旧请求由
 * TanStack Query 通过 AbortSignal 自动取消。 */
export function useEntryDetail(entryRef: string | null) {
  return useQuery({
    queryKey: ['entry', entryRef],
    queryFn: ({ signal }) => getEntry(entryRef!, signal),
    enabled: entryRef !== null,
  })
}

/** 状态写入（set 语义）。onSuccess 的 entryRef 必须取本次 mutation
 * 的 variables.entryRef——mutation 完成前 selection 可能已切到另一篇，
 * 读 Zustand selectedEntryRef 会 invalidate 错误的 key。 */
export function useEntryStateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      entryRef: string
      patch: { read: boolean } | { starred: boolean }
    }) => setEntryState(vars.entryRef, vars.patch),
    onSuccess: async (_data, variables) => {
      await Promise.all([
        // Detail 精确失效（用本次 mutation 的 entryRef，不是当前 selection）
        queryClient.invalidateQueries({
          queryKey: ['entry', variables.entryRef],
        }),
        // Entries 前缀失效：覆盖 all/unread/starred × 全部 feedUrl scope
        queryClient.invalidateQueries({ queryKey: ['entries'] }),
      ])
    },
  })
}
