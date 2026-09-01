/** TanStack Query hooks —— server state 的唯一入口。
 * useFeeds/useEntries 在 Sidebar / EntryList / ReaderPlaceholder 间共享
 * （同 query key 命中同一份 cache，不会重复请求）。 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getCategories,
  getEntries,
  getEntry,
  getFeeds,
  getFreshRssUiUrl,
  getSubscriptions,
  importOpml,
  moveSubscription,
  previewFeed,
  previewOpmlImport,
  renameCategory,
  setEntryState,
  subscribeFeed,
  unsubscribeFeed,
} from './client'
import type { UiView } from '../lib/read-later'
import { buildEntryQuery, scopeKey, type ContentScope } from '../lib/navigation'

export function useFeeds() {
  return useQuery({
    queryKey: ['feeds'],
    queryFn: ({ signal }) => getFeeds(signal),
  })
}

/** 0013 Gate 2：分类列表（含空分类；enabled=false 时完全不发请求）。 */
export function useCategories(enabled: boolean) {
  return useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) => getCategories(signal),
    enabled,
  })
}

/** 0013 Gate 3：订阅列表（管理视角，含 opaque subscriptionRef）。
 * 与 ['feeds'] 同一 FreshRSS truth，query key 独立（管理页可单独 refetch）。 */
export function useSubscriptions() {
  return useQuery({
    queryKey: ['subscriptions'],
    queryFn: ({ signal }) => getSubscriptions(signal),
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

/** 0013 Gate 2：直接 RSS/Atom 预览（无副作用 mutation —— 复用 mutation
 * 的 pending/error 语义，杜绝双击重复请求；不 invalidate 任何 query）。 */
export function useFeedPreviewMutation() {
  return useMutation({
    mutationFn: (feedUrl: string) => previewFeed(feedUrl),
  })
}

/** 0013 Gate 2：订阅（server-confirmed success → invalidate，不做
 * optimistic updates，不建第二套 Zustand subscription cache）。
 * Gate 3：订阅页改用 ['subscriptions'] 列表，一并失效。 */
export function useSubscribeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      feedUrl: string
      categoryId?: string | null
      title?: string | null
    }) => subscribeFeed(vars.feedUrl, vars),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** 0013 Gate 3：订阅结构变化后的统一 invalidate —— feeds（侧栏 RSS tree
 * + 订阅页分组）、categories（含空分类）、subscriptions（管理列表）、
 * entries（分类 stream / feed 归属可能变化）。全部 server-confirmed 后
 * 才调用，不做 optimistic updates。 */
async function invalidateSubscriptionState(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['feeds'] }),
    queryClient.invalidateQueries({ queryKey: ['categories'] }),
    queryClient.invalidateQueries({ queryKey: ['subscriptions'] }),
    queryClient.invalidateQueries({ queryKey: ['entries'] }),
  ])
}

/** 0013 Gate 3：移动订阅到已有分类。 */
export function useMoveSubscriptionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      subscriptionRef: string
      target: { categoryId: string } | { newCategoryLabel: string }
    }) => moveSubscription(vars.subscriptionRef, vars.target),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** 0013 Gate 3：取消订阅（破坏性；调用方必须先完成二次确认）。 */
export function useUnsubscribeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { subscriptionRef: string }) =>
      unsubscribeFeed(vars.subscriptionRef),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** 0013 Gate 3：重命名分类。分类 id（user/-/label/<名>）会随名字变化，
 * 旧 id 的 entries query cache 也一并失效。 */
export function useRenameCategoryMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { categoryId: string; label: string }) =>
      renameCategory(vars.categoryId, vars.label),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** 0013 Gate 4：OPML 导入预览（无副作用 mutation——复用 pending/error
 * 语义与双击防重；不 invalidate 任何 query，结果由调用方存本地 state）。 */
export function useOpmlPreviewMutation() {
  return useMutation({
    mutationFn: (file: File) => previewOpmlImport(file),
  })
}

/** 0013 Gate 4：确认 OPML 导入（merge；server-confirmed 后统一失效
 * 订阅相关 server state，与其它订阅 mutation 同一策略）。 */
export function useOpmlImportMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => importOpml(file),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** 0013 Gate 4：FreshRSS 高级逃生入口 URL（未配置 → null → UI 不渲染
 * 链接，绝不伪造入口）。 */
export function useFreshRssUiUrl() {
  return useQuery({
    queryKey: ['freshrss-ui'],
    queryFn: ({ signal }) => getFreshRssUiUrl(signal),
  })
}
