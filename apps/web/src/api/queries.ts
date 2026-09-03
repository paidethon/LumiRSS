/** TanStack Query hooks —— server state 的唯一入口。
 * useFeeds/useEntries 在 Sidebar / EntryList / ReaderPlaceholder 间共享
 * （同 query key 命中同一份 cache，不会重复请求）。 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  discoverFeeds,
  generateEntrySummary,
  generateEntryTranslation,
  getAiSettings,
  getCategories,
  getEntries,
  getEntry,
  getEntryConversation,
  getEntrySummary,
  getEntryTranslation,
  getFeeds,
  getFreshRssUiUrl,
  getRssHubRoutes,
  getSubscriptions,
  importOpml,
  moveSubscription,
  previewFeed,
  previewOpmlImport,
  previewRssHub,
  renameCategory,
  sendConversationMessage,
  setEntryState,
  subscribeFeed,
  unsubscribeFeed,
  updateAiSettings,
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

/** 0014：网站 → 候选发现（无副作用 mutation——复用 pending/error 语义
 * 与双击防重；不 invalidate 任何 query，结果由调用方存本地 state）。 */
export function useSourceDiscoveryMutation() {
  return useMutation({
    mutationFn: (url: string) => discoverFeeds(url),
  })
}

/** 0014：RSSHub 路由目录（static catalog；enabled=false 不发请求）。 */
export function useRssHubRoutes(enabled: boolean) {
  return useQuery({
    queryKey: ['rsshub-routes'],
    queryFn: ({ signal }) => getRssHubRoutes(signal),
    enabled,
  })
}

/** 0014：RSSHub 路由预览（无副作用 mutation；不 invalidate 任何 query，
 * 结果由调用方存本地 state；订阅仍走 useSubscribeMutation）。 */
export function useRssHubPreviewMutation() {
  return useMutation({
    mutationFn: (vars: { routeId: string; params: Record<string, string> }) =>
      previewRssHub(vars.routeId, vars.params),
  })
}

/** 0015：AI 设置（服务端持久化；enabled=false 时不发请求）。 */
export function useAiSettings(enabled: boolean = true) {
  return useQuery({
    queryKey: ['ai-settings'],
    queryFn: ({ signal }) => getAiSettings(signal),
    enabled,
  })
}

/** 0015：保存非机密 AI 设置。成功后失效 AI 设置与所有摘要/翻译状态
 * （model/language 参与缓存身份，旧缓存不再匹配 → Reader 诚实回到
 * not_generated，不展示过期结果）。 */
export function useUpdateAiSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (update: {
      baseUrl?: string
      model?: string
      summaryLanguage?: 'zh-CN' | 'en'
      translationLanguage?: 'zh-CN' | 'en'
    }) => updateAiSettings(update),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
        queryClient.invalidateQueries({ queryKey: ['entry-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['entry-translation'] }),
      ])
    },
  })
}

/** 0015：单篇摘要状态（GET 语义：只读缓存，绝不产生 provider 调用）。 */
export function useEntrySummary(entryRef: string | null) {
  return useQuery({
    queryKey: ['entry-summary', entryRef],
    queryFn: ({ signal }) => getEntrySummary(entryRef!, signal),
    enabled: entryRef !== null,
  })
}

/** 0015：显式生成摘要（POST；成功 = 服务端确认的状态，直接写回对应
 * entryRef 的 query cache；失败由调用方展示 + 重试）。 */
export function useGenerateSummaryMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => generateEntrySummary(entryRef),
    onSuccess: (data) => {
      queryClient.setQueryData(['entry-summary', entryRef], data)
    },
  })
}

/** 0016：单篇翻译状态（GET 语义：只读缓存，绝不产生 provider 调用）。 */
export function useEntryTranslation(entryRef: string | null) {
  return useQuery({
    queryKey: ['entry-translation', entryRef],
    queryFn: ({ signal }) => getEntryTranslation(entryRef!, signal),
    enabled: entryRef !== null,
  })
}

/** 0016：显式生成翻译（POST；成功状态写回对应 entryRef 的 query cache）。 */
export function useGenerateTranslationMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => generateEntryTranslation(entryRef),
    onSuccess: (data) => {
      queryClient.setQueryData(['entry-translation', entryRef], data)
    },
  })
}

/** 0016：文章限定对话（GET 语义：只读消息存储，绝不产生 provider 调用）。
 * enabled=false 时不发请求（对话面板关闭时零流量）。 */
export function useEntryConversation(entryRef: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['entry-conversation', entryRef],
    queryFn: ({ signal }) => getEntryConversation(entryRef!, signal),
    enabled: enabled && entryRef !== null,
  })
}

/** 0016：发送一条文章限定问题（POST；成功后把服务端确认的完整对话
 * 写回对应 entryRef 的 query cache；失败不持久化，输入保留以便重试）。 */
export function useSendConversationMessageMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => sendConversationMessage(entryRef, question),
    onSuccess: (data) => {
      queryClient.setQueryData(['entry-conversation', entryRef], data)
    },
  })
}
