/** TanStack Query hooks —— server state 的唯一入口。
 * useFeeds/useEntries 在 Sidebar / EntryList / ReaderPlaceholder 间共享
 * （同 query key 命中同一份 cache，不会重复请求）。 */

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  addLibraryFavorite,
  addWorkspaceItem,
  applyRssHubConfig,
  clearAiProfileSecret,
  clearDefaultAiSecret,
  clearLibreTranslateKey,
  clearRssHubSecret,
  createAiProfile,
  createBackup,
  createBookmark,
  createClip,
  createRssHubCredential,
  createSnapshot,
  createWorkspace,
  deleteAiProfile,
  deleteBookmark,
  deleteClip,
  deleteRssHubCredential,
  deleteSnapshot,
  deleteTag,
  deleteWorkspace,
  detectRssHub,
  discoverFeeds,
  executeRestore,
  fetchClipHtml,
  generateEntrySummary,
  generateEntryTranslation,
  generateTranslationSegments,
  getAiProfiles,
  getAiSettings,
  getBackupCapabilities,
  getBackupJob,
  getCategories,
  getClip,
  getEntries,
  getEntry,
  getEntryConversation,
  getEntrySummary,
  getEntryTranslation,
  getFeeds,
  getFreshRssUiUrl,
  getOperationsStatus,
  getRssHubConfig,
  getRssHubRoutes,
  getSubscriptions,
  getWebDavSettings,
  getWorkspaceContents,
  importBookmarks,
  importOpml,
  listBackups,
  listBookmarks,
  listClips,
  listRemoteBackups,
  listRssHubCredentials,
  listSnapshots,
  listTagsForItem,
  listWorkspaces,
  lookupTranslationSegments,
  moveSubscription,
  patchRssHubConfig,
  previewFeed,
  previewOpmlImport,
  previewRestore,
  previewRssHub,
  removeLibraryFavorite,
  removeWorkspaceItem,
  renameCategory,
  renameTag,
  renameWorkspace,
  reorderWorkspaceItems,
  saveLibreTranslateKey,
  searchEntries,
  sendConversationMessage,
  setAiProfileSecret,
  setDefaultAiSecret,
  setEntryState,
  setRssHubSecret,
  subscribeFeed,
  testLibreTranslate,
  testWebDav,
  unsubscribeFeed,
  updateAiProfile,
  updateAiPurposes,
  updateAiSettings,
  updateBookmark,
  updateWebDavSettings,
} from './client'
import type {
  AiProfileInput,
  ClipInput,
  FavoritesResponse,
  RssHubCredentialInput,
  TranslationSegmentBlockInput,
} from './client'
import type { AiPurposeKey } from './types'
import type { UiView } from '../lib/read-later'
import type { EntryDetail, EntryListItem } from './types'
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
 * 透传由 BFF scope envelope 保证不错乱。
 *
 * 内存有界（Phase H）：maxPages = 50（每页 20 条 → 缓存上限 1000 条
 * 列表 DTO，无正文）。刻意不取更小值：裁剪发生在「滚动加载下一页」
 * 的瞬间，Safari/iOS 没有浏览器 scroll anchoring，激进裁剪会让视口
 * 内容向前跳约一整页 —— 正常阅读深度（<1000 条）永远不触发裁剪，
 * 1000 条只是病态增长的内存保险丝。DOM 成本由列表行的
 * content-visibility 处理（见 EntryList）。staleTime 30s：scope/view
 * 来回切换不重复请求（数据仍由写路径的精确补丁保持精确）。 */
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
    maxPages: 50,
    staleTime: 30_000,
  })
}

/** 0022 全局搜索：q 已在页面侧防抖（300ms）；这里只负责无限分页。
 * staleTime 0：搜索期望每次输入都触发新请求；q 变化 = 换 key，
 * 旧请求由 AbortSignal 自动取消。enabled：空查询不发请求。
 * maxPages 50：与 entries 同一保险丝（正常搜索深度不触发裁剪，
 * 防病态增长；旧搜索 query 由 gcTime 正常回收）。 */
export function useSearch(
  q: string,
  filters: {
    feedUrl?: string | null
    categoryId?: string | null
    state?: 'unread' | null
    favorite?: boolean | null
  },
) {
  const trimmed = q.trim()
  return useInfiniteQuery({
    queryKey: ['search', { q: trimmed, ...filters }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      searchEntries(
        {
          q: trimmed,
          cursor: pageParam,
          feedUrl: filters.feedUrl ?? null,
          categoryId: filters.categoryId ?? null,
          state: filters.state ?? null,
          favorite: filters.favorite ?? null,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: trimmed.length > 0,
    placeholderData: keepPreviousData,
    maxPages: 50,
  })
}

/** 单篇 Detail。enabled：没有 selection（entryRef 为 null）时
 * 完全不发请求；切换 selection = 换 query key，旧请求由
 * TanStack Query 通过 AbortSignal 自动取消。
 * staleTime：正文对同一 entryRef 是稳定的（read/star 走 mutation 的
 * 精确失效）——快速来回切换时命中缓存，不重复 refetch 数百 KB 正文。 */
export function useEntryDetail(entryRef: string | null) {
  return useQuery({
    queryKey: ['entry', entryRef],
    queryFn: ({ signal }) => getEntry(entryRef!, signal),
    enabled: entryRef !== null,
    staleTime: 30_000,
  })
}

/** Phase H 工具：读取 query key 中的 view / 搜索过滤条件。 */
function entriesViewOf(key: readonly unknown[]): UiView {
  const second = key[1]
  if (second instanceof Object && 'view' in second) {
    return (second as { view: UiView }).view
  }
  return 'all'
}

function searchFiltersOf(
  key: readonly unknown[],
): { state: 'unread' | null; favorite: boolean | null } | null {
  const second = key[1]
  if (second instanceof Object && 'state' in second) {
    return second as { state: 'unread' | null; favorite: boolean | null }
  }
  return null
}

type EntriesPages = { items: EntryListItem[]; nextCursor: string | null }

/** 状态写入（set 语义）。onSuccess 的 entryRef 必须取本次 mutation
 * 的 variables.entryRef——mutation 完成前 selection 可能已切到另一篇，
 * 读 Zustand selectedEntryRef 会写错缓存。
 *
 * Phase H：写后不再全量 invalidate ['entries']（那会把所有 scope×view
 * 的已加载页全部重拉，滚动标记已读时每篇文章都触发一轮 —— 既是
 * CPU/网络浪费，也会与 maxPages 裁剪互相把页数放大回来）。改为精确
 * 缓存补丁：
 * - detail（['entry', ref]）：原地翻转标志（contentHtml 不动，零重拉）；
 * - 列表（['entries', …]）：all 视图翻转；unread 视图标记已读=移除；
 *   starred 视图取消收藏=移除；反向操作（需要重新插入列表的）只失效
 *   对应 view 的查询（罕见路径，下次挂载自然重拉）。
 * - 搜索缓存（['search', …]）：同样翻转/按过滤语义移除。 */
export function useEntryStateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      entryRef: string
      patch: { read: boolean } | { starred: boolean }
    }) => setEntryState(vars.entryRef, vars.patch),
    onSuccess: async (_data, variables) => {
      const { entryRef, patch } = variables

      // 1) Detail：原地翻转（不重拉正文）。
      queryClient.setQueryData<EntryDetail>(['entry', entryRef], (detail) =>
        detail
          ? {
              ...detail,
              read: 'read' in patch ? patch.read : detail.read,
              starred: 'starred' in patch ? patch.starred : detail.starred,
            }
          : detail,
      )

      // 2) 列表：逐 key 按 view 精确补丁。
      for (const [key, data] of queryClient.getQueriesData<{ pages: EntriesPages[] }>({
        queryKey: ['entries'],
      })) {
        if (!data) continue
        const view = entriesViewOf(key)
        queryClient.setQueryData(key, {
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            items: page.items.flatMap((item) => {
              if (item.entryRef !== entryRef) return [item]
              const next = {
                ...item,
                read: 'read' in patch ? patch.read : item.read,
                starred: 'starred' in patch ? patch.starred : item.starred,
              }
              // 服务端语义：unread 流里的已读条目、starred 流里的
              // 取消收藏条目，重拉后都会消失——补丁直接同步移除。
              if (view === 'unread' && next.read) return []
              if (view === 'starred' && !next.starred) return []
              return [next]
            }),
          })),
        })
      }

      // 3) 反向插入（unread 视图标记未读 / starred 视图加收藏）：无法
      // 精确插位，只失效对应 view（下次挂载重拉，staleTime 已覆盖
      // 常规切换）。只在对应方向发生时才失效，最小化重拉范围。
      if ('read' in patch ? !patch.read : patch.starred) {
        await queryClient.invalidateQueries({ queryKey: ['entries'] })
      }

      // 4) 搜索缓存：同样精确翻转/移除（unread/favorite 过滤的结果集
      // 语义同上）。
      for (const [key, data] of queryClient.getQueriesData<{
        pages: { items: EntryListItem[]; nextCursor: string | null }[]
      }>({ queryKey: ['search'] })) {
        if (!data) continue
        const filters = searchFiltersOf(key)
        queryClient.setQueryData(key, {
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            items: page.items.flatMap((item) => {
              if (item.entryRef !== entryRef) return [item]
              const next = {
                ...item,
                read: 'read' in patch ? patch.read : item.read,
                starred: 'starred' in patch ? patch.starred : item.starred,
              }
              if (filters?.state === 'unread' && next.read) return []
              if (filters?.favorite === true && !next.starred) return []
              return [next]
            }),
          })),
        })
      }
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
      translationEngine?: 'ai' | 'libretranslate' | 'browser'
      libretranslateUrl?: string
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

/** AI Profile 列表（元数据 + keyConfigured 布尔；绝不回显 key）。 */
export function useAiProfiles(enabled: boolean = true) {
  return useQuery({
    queryKey: ['ai-profiles'],
    queryFn: ({ signal }) => getAiProfiles(signal),
    enabled,
  })
}

/** Profile 增删改后统一失效：profile 列表 + AI 设置（purposeStatus 内嵌
 * 有效解析）+ 摘要/翻译/对话缓存身份（model 可能随 Profile 改变）。 */
async function invalidateAiProfileGraph(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['ai-profiles'] }),
    queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
    queryClient.invalidateQueries({ queryKey: ['entry-summary'] }),
    queryClient.invalidateQueries({ queryKey: ['entry-translation'] }),
  ])
}

export function useCreateAiProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: AiProfileInput) => createAiProfile(input),
    onSuccess: () => invalidateAiProfileGraph(queryClient),
  })
}

export function useUpdateAiProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { profileId: string; patch: Partial<AiProfileInput> }) =>
      updateAiProfile(vars.profileId, vars.patch),
    onSuccess: () => invalidateAiProfileGraph(queryClient),
  })
}

export function useDeleteAiProfileMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (profileId: string) => deleteAiProfile(profileId),
    onSuccess: () => invalidateAiProfileGraph(queryClient),
  })
}

/** Profile 密钥写入（write-only）。成功后只需刷新 key 状态视图。 */
export function useSetAiProfileSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { profileId: string; value: string }) =>
      setAiProfileSecret(vars.profileId, vars.value),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ai-profiles'] }),
        queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
      ])
    },
  })
}

export function useClearAiProfileSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (profileId: string) => clearAiProfileSecret(profileId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ai-profiles'] }),
        queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
      ])
    },
  })
}

export function useSetDefaultAiSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (value: string) => setDefaultAiSecret(value),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
  })
}

export function useClearDefaultAiSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => clearDefaultAiSecret(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-settings'] }),
  })
}

/** 用途分配（purpose → profileId）。成功后失效 AI 设置（purposeStatus）。 */
export function useUpdateAiPurposesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<Record<AiPurposeKey, string>>) =>
      updateAiPurposes(patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
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

// ---- 0018 Operations / RSSHub Control Center ----

export function useOperationsStatus() {
  return useQuery({
    queryKey: ['operations-status'],
    queryFn: ({ signal }) => getOperationsStatus(signal),
  })
}

export function useRssHubConfig(enabled: boolean = true) {
  return useQuery({
    queryKey: ['rsshub-config'],
    queryFn: ({ signal }) => getRssHubConfig(signal),
    enabled,
  })
}

export function usePatchRssHubConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: Record<string, number | string | boolean>) => patchRssHubConfig(values),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['rsshub-config'] }),
        queryClient.invalidateQueries({ queryKey: ['operations-status'] }),
      ])
    },
  })
}

export function useSetRssHubSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { key: string; value: string }) => setRssHubSecret(vars.key, vars.value),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rsshub-config'] })
    },
  })
}

export function useClearRssHubSecretMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (key: string) => clearRssHubSecret(key),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rsshub-config'] })
    },
  })
}

export function useApplyRssHubConfigMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => applyRssHubConfig(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['rsshub-config'] }),
        queryClient.invalidateQueries({ queryKey: ['operations-status'] }),
      ])
    },
  })
}

// ---- 0018 WebDAV / Backup / Restore ----

export function useWebDavSettings(enabled: boolean = true) {
  return useQuery({
    queryKey: ['webdav-settings'],
    queryFn: ({ signal }) => getWebDavSettings(signal),
    enabled,
  })
}

export function useUpdateWebDavSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      serverUrl?: string
      username?: string
      password?: string
      remoteDir?: string
      tlsVerify?: boolean
      clearPassword?: boolean
    }) => updateWebDavSettings(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['webdav-settings'] })
      await queryClient.invalidateQueries({ queryKey: ['operations-status'] })
    },
  })
}

export function useTestWebDavMutation() {
  return useMutation({
    mutationFn: () => testWebDav(),
  })
}

export function useBackups() {
  return useQuery({
    queryKey: ['backups'],
    queryFn: ({ signal }) => listBackups(signal),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? []
      const active = jobs.some((j) => j.status === 'queued' || j.status === 'running')
      return active ? 2000 : false
    },
  })
}

export function useBackupJob(id: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['backups', id],
    queryFn: ({ signal }) => getBackupJob(id!, signal),
    enabled: enabled && id !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'running' ? 1000 : false
    },
  })
}

export function useCreateBackupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (target: 'local' | 'webdav') => createBackup(target),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['backups'] }),
        queryClient.invalidateQueries({ queryKey: ['operations-status'] }),
      ])
    },
  })
}

export function useTranslationSegments(
  entryRef: string,
  blocks: TranslationSegmentBlockInput[] | null,
  enabled: boolean,
) {
  const blocksKey = blocks ? JSON.stringify(blocks) : ''
  return useQuery({
    queryKey: ['translation-segments', entryRef, blocksKey],
    queryFn: ({ signal }) =>
      lookupTranslationSegments(entryRef, blocks as TranslationSegmentBlockInput[], signal),
    // blocks 稳定后才有意义；同一内容版本的精确缓存永不重复请求
    enabled: enabled && blocks !== null && blocks.length > 0,
    staleTime: Infinity,
    gcTime: 10 * 60 * 1000,
  })
}

export function useGenerateTranslationSegmentsMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (blocks: TranslationSegmentBlockInput[]) =>
      generateTranslationSegments(entryRef, blocks),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['translation-segments', entryRef],
      })
    },
  })
}

export function useDetectRssHub() {
  return useQuery({
    queryKey: ['rsshub-detect'],
    queryFn: ({ signal }) => detectRssHub(signal),
  })
}

export function useRssHubCredentials() {
  return useQuery({
    queryKey: ['rsshub-credentials'],
    queryFn: ({ signal }) => listRssHubCredentials(signal),
  })
}

export function useCreateRssHubCredentialMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: RssHubCredentialInput) => createRssHubCredential(input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['rsshub-credentials'] }),
        queryClient.invalidateQueries({ queryKey: ['rsshub-config'] }),
      ])
    },
  })
}

export function useDeleteRssHubCredentialMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteRssHubCredential(id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['rsshub-credentials'] }),
        queryClient.invalidateQueries({ queryKey: ['rsshub-config'] }),
      ])
    },
  })
}

export function useSaveLibreTranslateKeyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (value: string) => saveLibreTranslateKey(value),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
    },
  })
}

export function useClearLibreTranslateKeyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => clearLibreTranslateKey(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
    },
  })
}

export function useTestLibreTranslateMutation() {
  return useMutation({
    mutationFn: () => testLibreTranslate(),
  })
}

export function useBackupCapabilities() {
  return useQuery({
    queryKey: ['backup-capabilities'],
    queryFn: ({ signal }) => getBackupCapabilities(signal),
  })
}

export function useRemoteBackups(enabled: boolean) {
  return useQuery({
    queryKey: ['backups-remote'],
    queryFn: ({ signal }) => listRemoteBackups(signal),
    enabled,
  })
}

export function useRestorePreviewMutation() {
  return useMutation({
    mutationFn: (source: { source: 'local' | 'remote'; jobId?: string; fileName?: string }) =>
      previewRestore(source),
  })
}

export function useRestoreExecuteMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { restoreSessionId: string; confirmation: string }) =>
      executeRestore(vars.restoreSessionId, vars.confirmation),
    onSuccess: async () => {
      // AUDIT-012：破坏性恢复替换了整个 Lumi 数据库——feeds/entries/
      // subscriptions/categories/AI/webdav/rsshub/backups 等全部缓存都
      // 已陈旧。无效化全部查询（而不仅 backups/operations），使各屏
      // 重拉恢复后的数据。（客户端设置在 RestoreWizard 中经 reload 重置。）
      await queryClient.invalidateQueries()
    },
  })
}

// ---- phase2 M1：书签（library/bookmarks） ----

/** 书签列表（q 已在页面侧防抖；cursor opaque 透传；与 search 同一
 * 无限分页模式，maxPages 保险丝一致）。 */
export function useBookmarks(q: string) {
  const trimmed = q.trim()
  return useInfiniteQuery({
    queryKey: ['library', 'bookmarks', { q: trimmed }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      listBookmarks({ q: trimmed || null, cursor: pageParam }, signal),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    placeholderData: keepPreviousData,
    maxPages: 50,
  })
}

/** 时间线「存书签」激活态依据：首页书签的 rssItemRef 集合（v1 取前
 * 500 条；created/delete 后由各 mutation 的前缀 invalidate 保持精确）。
 * staleTime 30s：时间线每行都调用本 hook（同 key 只发一次请求）。 */
export function useBookmarkRssRefs() {
  return useQuery({
    queryKey: ['library', 'bookmarks', 'rss-refs'],
    queryFn: ({ signal }) => listBookmarks({ limit: 500 }, signal),
    staleTime: 30_000,
  })
}

/** 创建书签（幂等）；成功后失效书签列表与 rss-refs 集合。 */
export function useCreateBookmarkMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      url?: string | null
      rssItemRef?: string | null
      title: string
      note?: string | null
    }) => createBookmark(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] })
    },
  })
}

export function useUpdateBookmarkMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      bookmarkRef: string
      patch: { title?: string | null; note?: string | null }
    }) => updateBookmark(vars.bookmarkRef, vars.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] })
    },
  })
}

export function useDeleteBookmarkMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (bookmarkRef: string) => deleteBookmark(bookmarkRef),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] })
    },
  })
}

/** Netscape HTML 导入（结果由调用方展示；成功后失效书签列表）。 */
export function useImportBookmarksMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => importBookmarks(file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'bookmarks'] })
    },
  })
}

// ---- phase2 M1：工作区（workspaces） ----

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: ({ signal }) => listWorkspaces(signal),
  })
}

export function useCreateWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => createWorkspace(name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })
}

/** 工作区内容（ResolvedItem 解析视图）。enabled：未选中工作区不发请求。 */
export function useWorkspaceContents(workspaceId: string | null) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'contents'],
    queryFn: ({ signal }) => getWorkspaceContents(workspaceId!, signal),
    enabled: workspaceId !== null,
  })
}

async function invalidateWorkspaceState(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    // 前缀覆盖：['workspace', id, 'items']（read-later 本地同步）与
    // ['workspace', id, 'contents']（本页解析视图）。
    queryClient.invalidateQueries({ queryKey: ['workspace'] }),
    // itemCount 徽标。
    queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  ])
}

export function useAddWorkspaceItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRef: string }) =>
      addWorkspaceItem(vars.workspaceId, vars.itemRef),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

export function useRemoveWorkspaceItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRef: string }) =>
      removeWorkspaceItem(vars.workspaceId, vars.itemRef),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

export function useReorderWorkspaceItemsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRefs: string[] }) =>
      reorderWorkspaceItems(vars.workspaceId, vars.itemRefs),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

/** P0-10：重命名工作区（保留工作区由 BFF 拒绝；UI 不为其提供入口）。
 * 成功后失效列表（名称/排序徽标）。 */
export function useRenameWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; name: string }) =>
      renameWorkspace(vars.workspaceId, vars.name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })
}

/** P0-10：删除工作区（破坏性；成员内容本身不删除，只解除归属）。
 * 失效列表 + 全部 contents 缓存（前缀覆盖 ['workspace']）。 */
export function useDeleteWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (workspaceId: string) => deleteWorkspace(workspaceId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
        queryClient.invalidateQueries({ queryKey: ['workspace'] }),
      ])
    },
  })
}

// ---- phase2 Gate 3：网页剪藏（library/clips） ----

/** 剪藏列表（cursor 分页；与 bookmarks 同一无限分页模式，maxPages
 * 保险丝一致）。 */
export function useClips() {
  return useInfiniteQuery({
    queryKey: ['library', 'clips'],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => listClips(pageParam, undefined, signal),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    placeholderData: keepPreviousData,
    maxPages: 50,
  })
}

/** 单条剪藏 Detail（含 contentHtml/contentText；Dialog 打开时才发
 * 请求——enabled=false 时零流量）。 */
export function useClipDetail(clipRef: string | null) {
  return useQuery({
    queryKey: ['library', 'clips', 'detail', clipRef],
    queryFn: ({ signal }) => getClip(clipRef!, signal),
    enabled: clipRef !== null,
  })
}

/** 服务端抓取目标页 HTML（无副作用 mutation——复用 pending/error
 * 语义与双击防重；不 invalidate 任何 query，结果由调用方进入提取
 * 流程后经 createClip 落库）。 */
export function useClipFetchMutation() {
  return useMutation({
    mutationFn: (url: string) => fetchClipHtml(url),
  })
}

/** 保存剪藏（幂等创建）；成功后失效剪藏列表与 detail 前缀。 */
export function useCreateClipMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ClipInput) => createClip(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

/** 删除剪藏（破坏性；调用方决定是否二次确认——本页与书签一致：
 * 行内立即删除）。 */
export function useDeleteClipMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (clipRef: string) => deleteClip(clipRef),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

// ---- phase2 Gate 3：网页快照（library/snapshots） ----

/** 快照列表 + 用量（count / bytes / quotaBytes）。 */
export function useSnapshots() {
  return useQuery({
    queryKey: ['library', 'snapshots'],
    queryFn: ({ signal }) => listSnapshots(signal),
  })
}

/** 生成快照（长任务 10–90s；server-confirmed 后失效快照列表）。 */
export function useCreateSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => createSnapshot(url),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'snapshots'] })
    },
  })
}

/** 删除快照（破坏性）。 */
export function useDeleteSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) => deleteSnapshot(uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'snapshots'] })
    },
  })
}

// ---- phase2 G6：API 来源 / 邮件简报 / Obsidian 库 / 联合收藏 ----
// 本节 client 函数在上方主 import 块之后按段引入（本文件约定 APPEND-ONLY，
// 新增 import 只能随新节追加在尾部；ESM 顶层 import 提升，行为等价）。

import {
  createApiSource,
  createMailBridgeList,
  deleteApiSource,
  deleteMailBridgeList,
  getDigestSettings,
  getFavorites,
  getObsidianNote,
  getObsidianStatus,
  listApiSources,
  listMailBridgeLists,
  listObsidianNotes,
  previewApiSource,
  rescanObsidian,
  sendDigestNow,
  updateApiSource,
  updateDigestSettings,
  updateObsidianSettings,
} from './client'
import type {
  ApiSourceCreateInput,
  ApiSourcePreviewInput,
  ApiSourceUpdateInput,
  DigestEntryRefInput,
  DigestSettingsUpdate,
} from './client'

// ---- API 来源 ----

export function useApiSources() {
  return useQuery({
    queryKey: ['api-sources'],
    queryFn: ({ signal }) => listApiSources(signal),
  })
}

export function useCreateApiSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ApiSourceCreateInput) => createApiSource(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
}

export function useUpdateApiSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { uuid: string; patch: ApiSourceUpdateInput }) =>
      updateApiSource(vars.uuid, vars.patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
}

export function useDeleteApiSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) => deleteApiSource(uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
}

/** 无副作用预览（不 invalidate 任何 query，结果由调用方存本地 state）。 */
export function useApiSourcePreviewMutation() {
  return useMutation({
    mutationFn: (input: ApiSourcePreviewInput) => previewApiSource(input),
  })
}

// ---- 邮件（收信地址 + 每日摘要） ----

export function useMailBridgeLists() {
  return useQuery({
    queryKey: ['mail', 'bridge-lists'],
    queryFn: ({ signal }) => listMailBridgeLists(signal),
  })
}

export function useCreateMailBridgeListMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => createMailBridgeList(name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['mail', 'bridge-lists'] })
    },
  })
}

export function useDeleteMailBridgeListMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) => deleteMailBridgeList(uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['mail', 'bridge-lists'] })
    },
  })
}

export function useDigestSettings() {
  return useQuery({
    queryKey: ['digest', 'settings'],
    queryFn: ({ signal }) => getDigestSettings(signal),
  })
}

export function useUpdateDigestSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: DigestSettingsUpdate) => updateDigestSettings(patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['digest', 'settings'] })
    },
  })
}

/** 立即发送（不 invalidate——lastSentAt/lastError 由下次进入设置时刷新）。 */
export function useSendDigestNowMutation() {
  return useMutation({
    mutationFn: (entryRefs: DigestEntryRefInput[]) => sendDigestNow(entryRefs),
  })
}

// ---- Obsidian 库 ----

export function useObsidianStatus() {
  return useQuery({
    queryKey: ['obsidian', 'status'],
    queryFn: ({ signal }) => getObsidianStatus(signal),
  })
}

/** 连接 Vault（server-confirmed 后失效整个 obsidian 前缀：status + notes）。 */
export function useConnectObsidianMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vaultPath: string) => updateObsidianSettings(vaultPath),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obsidian'] })
    },
  })
}

export function useObsidianRescanMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => rescanObsidian(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obsidian'] })
    },
  })
}

/** 笔记列表（q 已在页面侧防抖；placeholderData 避免输入切换闪空）。 */
export function useObsidianNotes(q: string) {
  const trimmed = q.trim()
  return useQuery({
    queryKey: ['obsidian', 'notes', { q: trimmed }],
    queryFn: ({ signal }) => listObsidianNotes({ q: trimmed || null, limit: 50 }, signal),
    placeholderData: keepPreviousData,
  })
}

/** 单条笔记 Detail（含 contentHtml；Dialog 打开时才发请求）。 */
export function useObsidianNoteDetail(noteRef: string | null) {
  return useQuery({
    queryKey: ['obsidian', 'notes', 'detail', noteRef],
    queryFn: ({ signal }) => getObsidianNote(noteRef!, signal),
    enabled: noteRef !== null,
  })
}

// ---- 联合收藏（展示层合并；RSS 真值仍走 ['entries'] starred 流） ----

export function useFavorites() {
  return useQuery({
    queryKey: ['favorites'],
    queryFn: ({ signal }) => getFavorites(signal),
  })
}

/** P0-10：库收藏增删（addLibraryFavorite/removeLibraryFavorite 首批 UI
 * 消费者）。乐观更新 ['favorites'] 的 library 腿：移除立即从列表消失；
 * 失败回滚到前值并重取（诚实错误由调用方从 mutation.error 透出）。 */
export function useLibraryFavoriteMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { ref: string; favorite: boolean }) =>
      vars.favorite ? addLibraryFavorite(vars.ref) : removeLibraryFavorite(vars.ref),
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: ['favorites'] })
      const previous = queryClient.getQueryData<FavoritesResponse>(['favorites'])
      queryClient.setQueryData<FavoritesResponse>(['favorites'], (old) => {
        if (old === undefined) return old
        if (!vars.favorite) {
          // 移除：行内数据可精确构造回滚前值 → 乐观过滤安全。
          return { ...old, library: old.library.filter((item) => item.ref !== vars.ref) }
        }
        return old
      })
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(['favorites'], context.previous)
      } else {
        void queryClient.invalidateQueries({ queryKey: ['favorites'] })
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['favorites'] })
    },
  })
}

/** P0-10：单条库内容的收藏状态 + 切换（UnifiedContentCard /
 * FavoritesPage LibraryRow 共用）。诚实语义：
 * - favorite = 服务端列表命中 ∨ 进行中的乐观添加（未落库前不假装完成）；
 * - pending 只在本人条目上；error 是本人条目最近一次失败（调用方原样
 *   透出，不吞不假装成功）。 */
export function useLibraryFavoriteToggle(ref: string) {
  const favorites = useFavorites()
  const mutation = useLibraryFavoriteMutation()
  const matchesVars = mutation.variables?.ref === ref
  const inList = favorites.data?.library.some((item) => item.ref === ref) ?? false
  const favorite =
    inList || (matchesVars && mutation.isPending && mutation.variables!.favorite)
  return {
    favorite,
    pending: matchesVars && mutation.isPending,
    error: matchesVars && mutation.isError ? mutation.error : null,
    toggle: () => mutation.mutate({ ref, favorite: !favorite }),
  }
}

// ---- phase2 G7/G8：Agent 工作台 / 标签 / 图谱 / RAG ----
// 本节 client 函数按段引入（本文件约定 APPEND-ONLY，新增 import 只能
// 随新节追加在尾部；ESM 顶层 import 提升，行为等价）。

import {
  assignTag,
  createAgentThread,
  decideAgentApproval,
  deleteAgentThread,
  getGraph,
  getRagStatus,
  listAgentMessages,
  listAgentThreads,
  listTags,
  sendAgentMessage,
  unassignTag,
} from './client'

/** 会话列表。 */
export function useAgentThreads() {
  return useQuery({
    queryKey: ['agent', 'threads'],
    queryFn: ({ signal }) => listAgentThreads(signal),
  })
}

export function useCreateAgentThreadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => createAgentThread(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'threads'] })
    },
  })
}

/** 删除会话（破坏性）：失效列表并移除该会话的消息缓存（无挂载中的
 * observer 时 removeQueries 直接丢弃，不触发重拉）。 */
export function useDeleteAgentThreadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (threadId: string) => deleteAgentThread(threadId),
    onSuccess: async (_data, threadId) => {
      queryClient.removeQueries({ queryKey: ['agent', 'messages', threadId] })
      await queryClient.invalidateQueries({ queryKey: ['agent', 'threads'] })
    },
  })
}

/** 会话消息（全量 after=0，增量去重交给服务端 seq 语义）。
 * refetchInterval：最新一条 role=assistant（本轮结束）或 approval
 * （等用户决定）→ 停止轮询；否则（user/tool/system/空）每 1s 轮询。
 * 批准/拒绝成功后由 mutation 失效本 key——新 tool 消息落到末尾，
 * 轮询自动恢复到 assistant 为止。 */
export function useAgentMessages(threadId: string | null) {
  return useQuery({
    queryKey: ['agent', 'messages', threadId],
    queryFn: ({ signal }) => listAgentMessages(threadId!, 0, signal),
    enabled: threadId !== null,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const last = items[items.length - 1]
      if (last !== undefined && (last.role === 'assistant' || last.role === 'approval')) {
        return false
      }
      return 1000
    },
  })
}

/** 发送一轮输入（202 processing → 轮询读回）。立即失效消息缓存，
 * 让用户消息尽快可见（循环在服务端异步运行）。 */
export function useSendAgentMessageMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => sendAgentMessage(threadId, text),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** 写操作批准/拒绝；成功后失效消息（decision 之后服务端续跑本轮）。 */
export function useAgentApprovalMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { approvalId: string; decision: 'approve' | 'reject' }) =>
      decideAgentApproval(threadId, vars.approvalId, vars.decision),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

// ---- 标签 ----

/** 标签列表（q 预留；图谱页取全量传 ''）。 */
export function useTags(q: string = '') {
  return useQuery({
    queryKey: ['tags', { q }],
    queryFn: ({ signal }) => listTags(q === '' ? null : q, signal),
  })
}

/** P0-10：单条内容的既有标签（条目标签选择面板用；null = 不发请求）。 */
export function useItemTags(itemRef: string | null) {
  return useQuery({
    queryKey: ['item-tags', itemRef],
    queryFn: ({ signal }) => listTagsForItem(itemRef!, signal),
    enabled: itemRef !== null,
  })
}

/** P0-10：给条目绑定标签（POST 幂等由 BFF 承载；失效条目标签 + 全列表）。 */
export function useAssignTagMutation(itemRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => assignTag({ itemRef, name, origin: 'manual' }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['item-tags', itemRef] }),
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
      ])
    },
  })
}

/** P0-10：解绑标签（DELETE；失效条目标签 + 全列表）。 */
export function useUnassignTagMutation(itemRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => unassignTag({ itemRef, name, origin: 'manual' }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['item-tags', itemRef] }),
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
      ])
    },
  })
}

/** P0-10：重命名标签（图谱页标签列表的行内管理入口；图谱/列表/条目标签
 * 全部失效）。 */
export function useRenameTagMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { tagId: number; name: string }) => renameTag(vars.tagId, vars.name),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
        queryClient.invalidateQueries({ queryKey: ['graph'] }),
        queryClient.invalidateQueries({ queryKey: ['item-tags'] }),
      ])
    },
  })
}

/** P0-10：删除标签（破坏性：解绑全部条目；图谱/列表/条目标签全部失效）。 */
export function useDeleteTagMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (tagId: number) => deleteTag(tagId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
        queryClient.invalidateQueries({ queryKey: ['graph'] }),
        queryClient.invalidateQueries({ queryKey: ['item-tags'] }),
      ])
    },
  })
}

// ---- 关系图谱 ----

/** 派生关系图（scope=all|workspace:<id>；max 2000，BFF 钳制）。
 * 纯只读视图：重建视图 = refetch。 */
export function useGraph(scope: string) {
  return useQuery({
    queryKey: ['graph', scope],
    queryFn: ({ signal }) => getGraph(scope, 2000, signal),
  })
}

// ---- RAG（Agent 页状态 chip；操作入口在设置页，本页只读展示） ----

export function useRagStatus(enabled: boolean = true) {
  return useQuery({
    queryKey: ['rag', 'status'],
    queryFn: ({ signal }) => getRagStatus(signal),
    enabled,
  })
}
