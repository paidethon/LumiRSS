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
  deletePasskey,
  disableTotp,
  enableTotp,
  finishPasskeyRegistration,
  getTotpStatus,
  getTodayQueue,
  generateTodayQueue,
  addQueueItem,
  removeQueueItem,
  setQueueItemDone,
  reorderTodayQueue,
  moveQueueItemSegment,
  setQueueSegmentOrder,
  freezeTodayQueue,
  getQueueSnapshots,
  getQueueSnapshot,
  deleteQueueSnapshot,
  listPasskeys,
  setupTotp,
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
  activateSummaryVersion,
  applyBacklog,
  createAuthorAlias,
  createInboxRule,
  createQaTemplate,
  createRelation,
  deleteAuthorAlias,
  deleteInboxRule,
  getAuthorAliases,
  getDiagnostics,
  getPinnedViewCount,
  getPinnedViews,
  getAuthorItems,
  getAuthors,
  getGlossaryHits,
  markNoTranslateBlock,
  unmarkNoTranslateBlock,
  getMissingDigestDates,
  generateDigestForDate,
  generateEntrySummaryScoped,
  previewBacklog,
  publishGptDigestIssue,
  deleteQaTemplate,
  deleteRelation,
  getQaTemplates,
  patchQaTemplate,
  pinSavedView,
  revokeAuthSession,
  unpinSavedView,
  getInboxRules,
  moveInboxRule,
  patchInboxRule,
  listAuthSessions,
  listRelationsForItem,
  deleteAiProfile,
  deleteBookmark,
  deleteClip,
  deleteRssHubCredential,
  deleteSnapshot,
  deleteTag,
  deleteWorkspace,
  detectRssHub,
  discoverFeeds,
  enableRag,
  getTagMergePreview,
  mergeTags,
  unlinkSavedSearchScope,
  undoTagMerge,
  executeRestore,
  fetchClipArticle,
  fetchDuplicateSuspects,
  fetchStaleSources,
  getSourceNotes,
  listSourceNotes,
  updateSourceNotes,
  batchMoveSubscriptions,
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
  translateEntryTitle,
  getEntryConversation,
  getEntrySummary,
  getEntryTranslation,
  getFeeds,
  getFreshRssNativeUrl,
  getFreshRssUiUrl,
  getOperationsStatus,
  getReadLaterTimeline,
  getRagStatus,
  getRssHubConfig,
  getRssHubFavorites,
  getRssHubRecent,
  getRssHubRouteHistory,
  getRssHubRoutes,
  refreshRssHubRoute,
  getSubscriptions,
  getWebDavSettings,
  getWorkspaceContents,
  getWorkspaceGroups,
  getWorkspaceResume,
  putWorkspaceResume,
  createInboxSource,
  deleteInboxItem,
  deleteInboxSource,
  importBookmarks,
  importOpml,
  listBackups,
  listBookmarks,
  listClips,
  listInboxItems,
  listSources,
  getMailImapSettings,
  testMailImap,
  pollMailImap,
  updateMailImapSettings,
  listInboxSources,
  listRemoteBackups,
  listRssHubCredentials,
  listSnapshots,
  listTagsForItem,
  listWorkspaceItems,
  listWorkspaces,
  listWorkspaceSnapshots,
  lookupTranslationSegments,
  moveSubscription,
  moveWorkspaceItemGroup,
  captureWorkspaceSnapshot,
  deleteWorkspaceSnapshot,
  restoreWorkspaceSnapshot,
  setWorkspaceItemPinned,
  patchRssHubConfig,
  previewFeed,
  previewOpmlImport,
  previewRestore,
  previewRssHub,
  putRssHubFavorite,
  rebuildRag,
  removeLibraryFavorite,
  removeWorkspaceItem,
  renameCategory,
  renameTag,
  renameWorkspace,
  reorderWorkspaceItems,
  resolveItems,
  saveLibreTranslateKey,
  searchEntries,
  createSavedSearchView,
  deleteRssHubFavorite,
  deleteSavedSearchView,
  getSavedSearchViews,
  renameSavedSearchView,
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
  enableViewFeedToken,
  rotateViewFeedToken,
  deleteTranslationSegmentRevision,
  putTranslationSegmentRevision,
  addDigestPoolEntry,
  applyStorageRetention,
  backfillMailImap,
  getDataFlows,
  getRetentionNotice,
  postponeRetention,
  previewBackupScope,
  verifyBackup,
  createMailRule,
  deleteMailRule,
  dryRunInboxIngest,
  dryRunMailRule,
  getMailParseDebug,
  getMailThread,
  getStorageRetention,
  listDigestPool,
  listInboxEvents,
  listMailRules,
  moveMailRule,
  patchMailRule,
  previewStorageRetention,
  putStorageRetention,
  removeDigestPoolEntry,
  replayInboxEvent,
  reorderDigestPool,
  rotateGptDigestFeedDryRun,
  rotateInboxSource,
  deleteSourceAlias,
  fetchUnsubscribePreview,
  listSourceAliasHistory,
  listSourceAliases,
  setSourceAlias,
} from './client'
import type {
  AiProfileInput,
  MailRuleCreateInput,
  ClipInput,
  FavoritesResponse,
  GptDigestConfigUpdate,
  GptDigestCreate,
  GptDigestIssueRevise,
  GptDigestSettingsUpdate,
  RssHubCredentialInput,
  TranslationSegmentBlockInput,
} from './client'
import type { AiPurposeKey, BackupScopeInclude } from './types'
import type { BacklogCondition } from './client'
import type { MailImapSettingsUpdate } from './client'
import type { UiView } from '../lib/read-later'
import type { EntryDetail, EntryListItem } from './types'
import type { TimelineOrder } from '../store/app-settings'
import { buildEntryQuery, scopeKey, type ContentScope } from '../lib/navigation'
import { READ_LATER_WORKSPACE_ID } from '../lib/read-later'

/** P0-01：稍后读时间线的 query key（toggle mutation 的乐观更新/失效
 * 都以这个精确 key 为目标；成员失效统一走 ['workspace', 'read-later']
 * 前缀，同时覆盖本 key 与 refs 清单 key）。 */
const READ_LATER_TIMELINE_KEY = ['workspace', READ_LATER_WORKSPACE_ID, 'timeline'] as const

/** 稍后读最近一次操作失败的信息（query cache 作最小事件通道：乐观移除
 * 会让行组件卸载，行级 mutation 实例的错误态随之丢失——失败信息写到
 * 这份 cache，由列表级 useReadLaterLastError 诚实展示；成功时清除。
 * key 刻意不在 ['workspace', …] 前缀下，避免被成员失效连带清掉）。 */
const READ_LATER_LAST_ERROR_KEY = ['read-later-last-error'] as const

/** 稍后读操作失败提示（列表级；乐观回滚已恢复数据，这里只补告警）。 */
export function useReadLaterLastError() {
  return useQuery({
    queryKey: READ_LATER_LAST_ERROR_KEY,
    queryFn: () => null as string | null,
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

/** 时间线缓存页形状（乐观移除用；entry 卡片字段此处不关心）。 */
interface ReadLaterTimelinePage {
  items: { itemRef: string }[]
  nextCursor: string | null
}

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
export function useEntries(scope: ContentScope, view: UiView, order: TimelineOrder = 'newest') {
  const entryQuery = buildEntryQuery(scope, view)
  return useInfiniteQuery({
    // N034：order 进入 queryKey —— received 走服务端 ?sort=received，
    // 切换排序 = 换 key（与 read-later 时间线同一模式）。
    queryKey: ['entries', { view, scope: scopeKey(scope), order }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      getEntries(
        {
          view: entryQuery.view,
          feedUrl: entryQuery.feedUrl,
          sourceType: entryQuery.sourceType,
          categoryId: entryQuery.categoryId,
          cursor: pageParam,
          sort: order === 'received' ? 'received' : null,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    maxPages: 50,
    staleTime: 30_000,
    // P0-01：read-later 不再映射 view=all 客户端过滤——它走服务端时间线
    // useReadLaterTimeline；这里对 read-later 视图禁用（零流量）。
    enabled: view !== 'read-later',
  })
}

/** P0-01：服务端稍后读时间线（最新加入在前；cursor opaque；悬挂成员
 * stale 行可见）。read-later 视图的唯一数据源——服务端是真源（ADR 0004）。 */
export function useReadLaterTimeline(order: 'newest' | 'oldest' = 'newest') {
  return useInfiniteQuery({
    // order 进入 queryKey：切换排序 = 换 key（cursor 自动重置，不重复）。
    queryKey: [...READ_LATER_TIMELINE_KEY, { order }],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      getReadLaterTimeline({ cursor: pageParam, limit: 25, order }, signal),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    maxPages: 50,
    staleTime: 30_000,
  })
}

/** 稍后读成员 ref 清单（Clock 按钮激活态真源；与时间线同一失效前缀）。 */
export function useReadLaterRefs() {
  return useQuery({
    queryKey: ['workspace', READ_LATER_WORKSPACE_ID, 'items'],
    queryFn: ({ signal }) => listWorkspaceItems(READ_LATER_WORKSPACE_ID, signal),
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
    /** F078：同义词扩展（客户端默认开，可本次关闭）。 */
    expandSynonyms?: boolean
  },
) {
  const trimmed = q.trim()
  return useInfiniteQuery({
    queryKey: [...SEARCH_RESULTS_KEY, { q: trimmed, ...filters }],
    // 双腿独立 keyset（pool #10）：RSS 腿与库腿各自推进；某腿耗尽后
    // 传 null，服务端据此跳过该腿（null cursor + 非 null
    // libraryCursor = RSS 腿已取完，只续库腿）。
    initialPageParam: { cursor: null, libraryCursor: null } as {
      cursor: string | null
      libraryCursor: string | null
    },
    queryFn: ({ pageParam, signal }) =>
      searchEntries(
        {
          q: trimmed,
          cursor: pageParam.cursor,
          libraryCursor: pageParam.libraryCursor,
          feedUrl: filters.feedUrl ?? null,
          categoryId: filters.categoryId ?? null,
          state: filters.state ?? null,
          favorite: filters.favorite ?? null,
          expandSynonyms: filters.expandSynonyms,
        },
        signal,
      ),
    getNextPageParam: (lastPage) => {
      const rssDone = !lastPage.hasMore || lastPage.nextCursor == null
      const libraryDone =
        !lastPage.libraryHasMore || lastPage.libraryNextCursor == null
      if (rssDone && libraryDone) return undefined
      return {
        cursor: rssDone ? null : lastPage.nextCursor,
        libraryCursor: libraryDone ? null : lastPage.libraryNextCursor!,
      }
    },
    enabled: trimmed.length > 0,
    placeholderData: keepPreviousData,
    maxPages: 50,
  })
}

/** 搜索缓存 key 分层（P0 2026-09-18）：分页结果与保存视图清单是两种
 * 缓存形状（InfiniteData vs 普通 list）。曾共用 ['search'] 裸前缀，
 * useEntryStateMutation 按 ['search'] 枚举时把清单误当 InfiniteData 调
 * data.pages.map —— 服务端已 204，前端成功回调仍抛「n.pages.map
 * undefined」并误报「状态更新失败」。此后任何搜索子缓存必须挂在
 * ['search', <子空间>, …] 下，状态写入只枚举 results 子空间。 */
export const SEARCH_RESULTS_KEY = ['search', 'results'] as const

const SAVED_VIEWS_KEY = ['search', 'saved-views'] as const

/** pool #09：保存的搜索视图清单（存查询+筛选意图，不是结果集）。 */
export function useSavedSearchViews() {
  return useQuery({
    queryKey: SAVED_VIEWS_KEY,
    queryFn: ({ signal }) => getSavedSearchViews(signal),
    staleTime: 30_000,
  })
}

export function useCreateSavedSearchViewMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      name: string
      query: string
      view: string
      categoryKey: string
      workspaceId?: string | null
      contentTypes?: string[] | null
    }) => createSavedSearchView(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SAVED_VIEWS_KEY })
    },
  })
}

/** N144：解除已失效的工作区关联（保存视图列表即时刷新）。 */
export function useUnlinkSavedSearchScopeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => unlinkSavedSearchScope(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SAVED_VIEWS_KEY })
    },
  })
}

export function useRenameSavedSearchViewMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      renameSavedSearchView(id, name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SAVED_VIEWS_KEY })
    },
  })
}

export function useDeleteSavedSearchViewMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteSavedSearchView(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SAVED_VIEWS_KEY })
    },
  })
}

/** F061：启用/轮换视图私有 Atom 订阅 token；成功后失效视图列表
 * （hasFeedToken 布尔更新）。atomPath 仅在响应中出现一次。 */
export function useViewFeedTokenMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'enable' | 'rotate' }) =>
      action === 'enable' ? enableViewFeedToken(id) : rotateViewFeedToken(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: SAVED_VIEWS_KEY })
    },
  })
}

/** 单篇 Detail。enabled：没有 selection（entryRef 为 null）时
 * 完全不发请求；切换 selection = 换 query key，旧请求由
 * TanStack Query 通过 AbortSignal 自动取消。
 * staleTime：正文对同一 entryRef 是稳定的（read/star 走 mutation 的
 * 精确失效）——快速来回切换时命中缓存，不重复 refetch 数百 KB 正文。 */export function useEntryDetail(entryRef: string | null) {
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
  // key 布局固定为 ['search', 'results', { filters }]（见 SEARCH_RESULTS_KEY）。
  const filters = key[2]
  if (filters instanceof Object && 'state' in filters) {
    return filters as { state: 'unread' | null; favorite: boolean | null }
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
 * - 搜索缓存（['search', 'results', …]）：同样翻转/按过滤语义移除。 */
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
      // 语义同上）。只枚举 results 子空间——['search'] 裸前缀会把保存
      // 视图清单（普通 query）误当 InfiniteData（P0 2026-09-18）。
      for (const [key, data] of queryClient.getQueriesData<{
        pages: { items: EntryListItem[]; nextCursor: string | null }[]
      }>({ queryKey: SEARCH_RESULTS_KEY })) {
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

/** 0013 Gate 3 / N012：取消订阅（破坏性；调用方必须先完成二次确认）。
 *  keepArtifacts：true=保留批注/工作区引用；false=显式清理；缺省=legacy。 */
export function useUnsubscribeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { subscriptionRef: string; keepArtifacts?: boolean }) =>
      unsubscribeFeed(vars.subscriptionRef, vars.keepArtifacts),
    onSuccess: () => invalidateSubscriptionState(queryClient),
  })
}

/** N012：退订影响预览（只读；对话框打开时拉取，确认前必须可见）。 */
export function useUnsubscribePreviewQuery(subscriptionRef: string | null) {
  return useQuery({
    queryKey: ['unsubscribe-preview', subscriptionRef],
    queryFn: ({ signal }) => {
      void signal
      return fetchUnsubscribePreview(subscriptionRef as string)
    },
    enabled: subscriptionRef !== null,
    staleTime: 0,
    gcTime: 0,
  })
}

/** N013：全部来源别名（展示「服务端赢」；本地 localStorage 只是离线回退）。 */
export function useSourceAliasesQuery(enabled = true) {
  return useQuery({
    queryKey: ['source-aliases'],
    queryFn: listSourceAliases,
    enabled,
    staleTime: 60_000,
    retry: false,
  })
}

/** N013：设置/更名来源别名（服务端真源；成功后失效别名缓存）。 */
export function useSetSourceAliasMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { feedUrl: string; customName: string }) =>
      setSourceAlias(vars.feedUrl, vars.customName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['source-aliases'] })
    },
  })
}

/** N013：清除来源别名（历史保留；成功后失效别名缓存）。 */
export function useDeleteSourceAliasMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (feedUrl: string) => deleteSourceAlias(feedUrl),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['source-aliases'] })
    },
  })
}

/** N013：某来源的改名历史（对话框打开时才拉取）。 */
export function useSourceAliasHistoryQuery(feedUrl: string | null) {
  return useQuery({
    queryKey: ['source-alias-history', feedUrl],
    queryFn: () => listSourceAliasHistory(feedUrl as string),
    enabled: feedUrl !== null,
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
 * 订阅相关 server state，与其它订阅 mutation 同一策略）。
 * F002：vars 可携带 selectedIndexes（仅导入勾选项）。 */
export function useOpmlImportMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { file: File; selectedIndexes?: number[] }) =>
      importOpml(vars.file, vars.selectedIndexes),
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

/** P09 委托入口：FreshRSS 原生界面坐标（{origin, username}）。绑定待定
 * → 409（isError），UI 显示诚实待定文案、绝不渲染假链接。409 是「正常
 * 的待定数据状态」而非故障，不做自动重试。 */
export function useFreshRssNativeUrl() {
  return useQuery({
    queryKey: ['freshrss-native-url'],
    queryFn: ({ signal }) => getFreshRssNativeUrl(signal),
    retry: false,
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

/** N021：路由收藏（服务端持久化，跨设备）。 */
export function useRssHubFavorites(enabled: boolean) {
  return useQuery({
    queryKey: ['rsshub-favorites'],
    queryFn: ({ signal }) => getRssHubFavorites(signal),
    enabled,
  })
}

/** N021：最近使用（仅成功 preview/subscribe 过的路由）。 */
export function useRssHubRecent(enabled: boolean) {
  return useQuery({
    queryKey: ['rsshub-recent'],
    queryFn: ({ signal }) => getRssHubRecent(signal),
    enabled,
  })
}

/** N021：收藏 / 改标签（成功后失效收藏缓存）。 */
export function usePutRssHubFavoriteMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { routeId: string; params?: Record<string, string>; label?: string }) =>
      putRssHubFavorite(vars),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rsshub-favorites'] })
    },
  })
}

/** N021：取消收藏（成功后失效收藏缓存）。 */
export function useDeleteRssHubFavoriteMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (routeKey: string) => deleteRssHubFavorite(routeKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rsshub-favorites'] })
    },
  })
}

/** N025：路由健康时间线（routeKey 为 null 时不发请求——预览前无 key）。 */
export function useRssHubRouteHistory(routeKey: string | null) {
  return useQuery({
    queryKey: ['rsshub-route-history', routeKey],
    queryFn: ({ signal }) => getRssHubRouteHistory(routeKey as string, signal),
    enabled: routeKey !== null,
  })
}

/** N027：强制重取单路由（成功后失效该路由时间线缓存）。 */
export function useRssHubRefreshMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (routeKey: string) => refreshRssHubRoute(routeKey),
    onSuccess: async (_data, routeKey) => {
      await queryClient.invalidateQueries({
        queryKey: ['rsshub-route-history', routeKey],
      })
    },
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
        // 目标语言参与 segments 服务端结果，双保险：换键 + 显式失效。
        queryClient.invalidateQueries({ queryKey: ['translation-segments'] }),
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
    mutationFn: (vars: { target: 'local' | 'webdav'; include?: BackupScopeInclude }) =>
      createBackup(vars.target, vars.include),
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
  targetLanguage: string,
) {
  const blocksKey = blocks ? JSON.stringify(blocks) : ''
  return useQuery({
    // targetLanguage 参与缓存身份：服务端按设置的目标语言产出译文，
    // 语言切换后旧缓存不再匹配（staleTime: Infinity 下不换键就永远错）。
    queryKey: ['translation-segments', entryRef, targetLanguage, blocksKey],
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
    mutationFn: ({
      blocks,
      overwriteRevisions,
    }: {
      blocks: TranslationSegmentBlockInput[]
      /** F062：显式覆盖 = 撤销手工修订段并重新生成。 */
      overwriteRevisions?: boolean
    }) => generateTranslationSegments(entryRef, blocks, { overwriteRevisions }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['translation-segments', entryRef],
      })
    },
  })
}

/** F062：保存/撤销一段译文的手工修订；成功后失效该篇的段查询。 */
export function useTranslationSegmentRevisionMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      blockIndex,
      text,
    }: {
      blockIndex: number
      text: string | null
    }) =>
      text === null
        ? deleteTranslationSegmentRevision(entryRef, blockIndex).then(() => null)
        : putTranslationSegmentRevision(entryRef, blockIndex, text),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['translation-segments', entryRef],
      })
    },
  })
}

/** N086：标记/撤销一块「不翻译」；成功后失效该篇的段查询。 */
export function useNoTranslateBlockMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      blockIndex,
      marked,
    }: {
      blockIndex: number
      marked: boolean
    }) =>
      marked
        ? markNoTranslateBlock(entryRef, blockIndex)
        : unmarkNoTranslateBlock(entryRef, blockIndex),
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

// ---- N181 数据外发 / N185 备份范围 / N186 独立自检 ----

/** N181：逐来源数据外发清单（服务端真实配置；只读）。 */
export function useDataFlows() {
  return useQuery({
    queryKey: ['privacy', 'data-flows'],
    queryFn: ({ signal }) => getDataFlows(signal),
    staleTime: 30_000,
  })
}

/** N185：备份内容选择预览（只读；不创建任务）。 */
export function usePreviewBackupScopeMutation() {
  return useMutation({
    mutationFn: (include?: Partial<BackupScopeInclude>) => previewBackupScope(include),
  })
}

/** N186：独立完整性自检（只出报告，不建恢复会话）。 */
export function useBackupVerifyMutation() {
  return useMutation({
    mutationFn: (body: { source: 'local' | 'remote'; jobId?: string; fileName?: string }) =>
      verifyBackup(body),
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
    mutationFn: (vars: { workspaceId: string; itemRef: string; force?: boolean }) =>
      removeWorkspaceItem(vars.workspaceId, vars.itemRef, { force: vars.force }),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

/** P0-01：稍后读成员增删（set 语义；时间线乐观更新 + 失败回滚 +
 * 诚实错误，镜像 useLibraryFavoriteMutation 模式）。
 * - 移除：onMutate 从时间线缓存各页精确移除该行（立即消失）；
 * - 添加：无法本地构造完整卡片（entry 由服务端投影）→ 不伪造乐观行，
 *   onSuccess 失效时间线后新行出现在头部（时间线视图外的添加本就不
 *   需要即时可见）；
 * - 失败：回滚到前值（无前值则失效重取）；错误由调用方从 mutation
 *   原样透出（变量匹配该行才显示，不串行）。 */
export function useReadLaterMemberMutation() {
  const queryClient = useQueryClient()
  return useMutation<
    void,
    Error,
    { itemRef: string; add: boolean },
    { previous: { pages: ReadLaterTimelinePage[] } | undefined }
  >({
    mutationFn: async (vars) => {
      // itemRef 是完整存储形态（rss:<id> / library:<uuid>）——按域加前缀
      // 曾把 library ref 变成 rss:library:…，收件条目永远删不掉（Q-P1-05）。
      if (vars.add) {
        await addWorkspaceItem(READ_LATER_WORKSPACE_ID, vars.itemRef)
        return
      }
      await removeWorkspaceItem(READ_LATER_WORKSPACE_ID, vars.itemRef)
    },
    onMutate: async (vars) => {
      queryClient.setQueryData<string | null>(READ_LATER_LAST_ERROR_KEY, null)
      if (vars.add) return { previous: undefined }
      await queryClient.cancelQueries({ queryKey: READ_LATER_TIMELINE_KEY })
      const previous = queryClient.getQueryData<{ pages: ReadLaterTimelinePage[] }>(
        READ_LATER_TIMELINE_KEY,
      )
      queryClient.setQueryData<{ pages: ReadLaterTimelinePage[] }>(
        READ_LATER_TIMELINE_KEY,
        (old) =>
          old === undefined
            ? old
            : {
                ...old,
                pages: old.pages.map((page) => ({
                  ...page,
                  items: page.items.filter(
                    (it) => it.itemRef !== vars.itemRef,
                  ),
                })),
              },
      )
      return { previous }
    },
    onError: (error, _vars, context) => {
      // 失败信息写入共享 cache：乐观移除会让行组件卸载（行级实例的错误
      // 态丢失），列表级观察者据此诚实补告警。
      queryClient.setQueryData<string | null>(
        READ_LATER_LAST_ERROR_KEY,
        error instanceof Error ? error.message : '稍后读操作失败，请稍后重试。',
      )
      if (context?.previous !== undefined) {
        queryClient.setQueryData(READ_LATER_TIMELINE_KEY, context.previous)
      } else {
        void queryClient.invalidateQueries({ queryKey: READ_LATER_TIMELINE_KEY })
      }
    },
    onSettled: () => {
      // 前缀覆盖：时间线、refs 清单、（其它）工作区 contents。
      void queryClient.invalidateQueries({
        queryKey: ['workspace', READ_LATER_WORKSPACE_ID],
      })
    },
  })
}

export function useReorderWorkspaceItemsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRefs: string[]; expectedRevision?: number }) =>
      reorderWorkspaceItems(vars.workspaceId, vars.itemRefs, vars.expectedRevision),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

/** N101：分组视图（固定区 + 未分组隐式前置组 + 命名组序列）。 */
export function useWorkspaceGroups(workspaceId: string | null) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'groups'],
    queryFn: ({ signal }) => getWorkspaceGroups(workspaceId!, signal),
    enabled: workspaceId !== null,
  })
}

/** N101：移动条目到分组（groupName=null = 移回未分组）。 */
export function useSetItemGroupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRef: string; groupName: string | null }) =>
      moveWorkspaceItemGroup(vars.workspaceId, vars.itemRef, vars.groupName),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

/** N102：设置固定标记（set 语义非 toggle）。 */
export function useSetItemPinnedMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRef: string; pinned: boolean }) =>
      setWorkspaceItemPinned(vars.workspaceId, vars.itemRef, vars.pinned),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

// ---- N105：工作区会话快照 ----

export function useWorkspaceSessionSnapshots(workspaceId: string | null) {
  return useQuery({
    queryKey: ['workspace-snapshots', workspaceId],
    queryFn: ({ signal }) => listWorkspaceSnapshots(workspaceId!, signal),
    enabled: workspaceId !== null,
  })
}

export function useCaptureWorkspaceSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; name: string }) =>
      captureWorkspaceSnapshot(vars.workspaceId, vars.name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspace-snapshots'] })
    },
  })
}

export function useDeleteWorkspaceSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; snapshotId: string }) =>
      deleteWorkspaceSnapshot(vars.workspaceId, vars.snapshotId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workspace-snapshots'] })
    },
  })
}

/** 恢复快照；成功后失效工作区全部状态（顺序/分组/固定/成员都可能变）。 */
export function useRestoreWorkspaceSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      workspaceId: string
      snapshotId: string
      mode: 'reorder' | 'replace'
      force?: boolean
    }) =>
      restoreWorkspaceSnapshot(
        vars.workspaceId,
        vars.snapshotId,
        vars.mode,
        vars.force ?? false,
      ),
    onSuccess: () => invalidateWorkspaceState(queryClient),
  })
}

/** P15：续读指针查询（每工作区一个；pointer=null = 无）。 */
export function useWorkspaceResume(workspaceId: string | null) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'resume'],
    queryFn: ({ signal }) => getWorkspaceResume(workspaceId!, signal),
    enabled: workspaceId !== null,
  })
}

/** P15：保存续读指针（条目打开时调用；失败静默降级——指针是体验增强，
 * 不应因一次 404/网络错误打断阅读动作本身）。 */
export function usePutWorkspaceResumeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; itemRef: string }) =>
      putWorkspaceResume(vars.workspaceId, vars.itemRef),
    onSuccess: (_data, vars) => {
      void queryClient.invalidateQueries({
        queryKey: ['workspace', vars.workspaceId, 'resume'],
      })
    },
  })
}

/** P0-10：重命名工作区（保留工作区由 BFF 拒绝；UI 不为其提供入口）。
 * 成功后失效列表（名称/排序徽标）。 */
export function useRenameWorkspaceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { workspaceId: string; name: string; description?: string }) => {
      // F25：description 未提供时不携带该字段（旧调用方/测试契约不变）
      if (vars.description === undefined) {
        return renameWorkspace(vars.workspaceId, vars.name)
      }
      return renameWorkspace(vars.workspaceId, vars.name, vars.description)
    },
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

/** P0-03：服务端抓取并提取目标页文章（无副作用 mutation——复用
 * pending/error 语义与双击防重；不 invalidate 任何 query，结果由调用方
 * 进入确认流程后经 createClip({url, finalUrl}) 落库）。 */
export function useClipFetchMutation() {
  return useMutation({
    mutationFn: (url: string) => fetchClipArticle(url),
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
  generateGptDigest,
  generateConfigDigest,
  getConfigFeed,
  getGptDigestFeed,
  compareFactsGptDigestIssue,
  compareGptDigestIssue,
  explainGptDigestIssue,
  generateWeeklyDigest,
  snoozeReadLaterItem,
  getGptDigestSettings,
  listConfigIssues,
  listGptDigestConfigs,
  listGptDigestIssues,
  listNotesByEntry,
  getDigestTrimPreview,
  previewConfigDigest,
  previewGptDigest,
  retryPolishGptDigestIssue,
  reviseGptDigestIssue,
  rotateGptDigestFeed,
  setSourceOverride,
  updateGptDigestConfig,
  createGptDigestConfig,
  deleteGptDigestConfig,
  updateGptDigestSettings,
  getFavorites,
  getObsidianNote,
  getObsidianStatus,
  getObsidianExportTemplate,
  clearObsidianHandoffLog,
  confirmObsidianHandoff,
  createObsidianDevice,
  updateObsidianDevice,
  deleteObsidianDevice,
  getAnnotationsExportDelta,
  listApiSources,
  getCleanupSuggestions,
  listMailBridgeLists,
  listObsidianDevices,
  listObsidianHandoffLog,
  listObsidianNotes,
  listStagedSources,
  previewApiSource,
  previewApiSourceSample,
  previewObsidianExportTemplate,
  requestObsidianExportHandoff,
  rescanObsidian,
  rotateApiSourceCredential,
  sendDigestNow,
  stageSource,
  subscribeStagedSource,
  discardStagedSource,
  testApiSourceCredential,
  updateApiSource,
  updateDigestSettings,
  updateObsidianExportTemplate,
  updateObsidianSettings,
  applyCleanupSuggestions,
  validateObsidianExport,
} from './client'
import type {
  ApiSourceCreateInput,
  ApiSourcePreviewInput,
  ApiSourceSamplePreviewInput,
  ApiSourceUpdateInput,
  DigestEntryRefInput,
  DigestSettingsUpdate,
  ObsidianDeviceProfilePayload,
  ObsidianExportTemplateView,
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

// ---- N128 用样例预览 / N130 轮换；N011 组合包 / N016 暂存 / N017 清理建议 ----

export function useApiSourceSamplePreviewMutation() {
  return useMutation({
    mutationFn: (input: ApiSourceSamplePreviewInput) => previewApiSourceSample(input),
  })
}

export function useTestApiSourceCredentialMutation() {
  return useMutation({
    mutationFn: (vars: { uuid: string; newCredential: string }) =>
      testApiSourceCredential(vars.uuid, vars.newCredential),
  })
}

export function useRotateApiSourceCredentialMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { uuid: string; newCredential: string }) =>
      rotateApiSourceCredential(vars.uuid, vars.newCredential),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['api-sources'] })
    },
  })
}

export function useStagedSources() {
  return useQuery({
    queryKey: ['sources', 'staging'],
    queryFn: ({ signal }) => listStagedSources(signal),
  })
}

export function useStageSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { url: string; note?: string }) => stageSource(vars.url, vars.note),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['sources', 'staging'] })
    },
  })
}

export function useSubscribeStagedSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => subscribeStagedSource(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['sources', 'staging'] })
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    },
  })
}

export function useDiscardStagedSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => discardStagedSource(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['sources', 'staging'] })
    },
  })
}

export function useCleanupSuggestions() {
  return useQuery({
    queryKey: ['sources', 'cleanup-suggestions'],
    queryFn: ({ signal }) => getCleanupSuggestions(signal),
  })
}

export function useApplyCleanupSuggestionsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      feedUrls: string[]
      action: 'mute' | 'demote_category'
      targetCategoryLabel?: string
    }) => applyCleanupSuggestions(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['sources', 'cleanup-suggestions'] })
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    },
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

// ---- M4：GPT 日报 ----

export function useGptDigestSettings() {
  return useQuery({
    queryKey: ['gpt-digest', 'settings'],
    queryFn: ({ signal }) => getGptDigestSettings(signal),
  })
}

export function useGptDigestIssues() {
  return useQuery({
    queryKey: ['gpt-digest', 'issues'],
    queryFn: ({ signal }) => listGptDigestIssues(signal),
  })
}

export function useUpdateGptDigestSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: GptDigestSettingsUpdate) => updateGptDigestSettings(patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest', 'settings'] })
    },
  })
}

export function useGptDigestFeed() {
  return useQuery({
    queryKey: ['gpt-digest', 'feed'],
    queryFn: () => getGptDigestFeed(),
  })
}

export function useRotateGptDigestFeedMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => rotateGptDigestFeed(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest', 'feed'] })
    },
  })
}

/** 立即生成（成功后失效 settings + issues：lastIssueKey/lastError/期刊列表）。 */
export function useGenerateGptDigestMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => generateGptDigest(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
  })
}

/** 选材预览（F06）：按需触发，不进缓存失效体系。 */
export function useGptDigestPreviewMutation() {
  return useMutation({ mutationFn: () => previewGptDigest() })
}

// ---- F01：多配置 ----

export function useGptDigestConfigs() {
  return useQuery({
    queryKey: ['gpt-digest', 'configs'],
    queryFn: ({ signal }) => listGptDigestConfigs(signal),
  })
}

function useInvalidateGptDigest() {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
  }
}

export function useCreateGptDigestConfigMutation() {
  const invalidate = useInvalidateGptDigest()
  return useMutation({
    mutationFn: (payload: GptDigestCreate) => createGptDigestConfig(payload),
    onSuccess: invalidate,
  })
}

export function useUpdateGptDigestConfigMutation() {
  const invalidate = useInvalidateGptDigest()
  return useMutation({
    mutationFn: ({ configId, patch }: { configId: number; patch: GptDigestConfigUpdate }) =>
      updateGptDigestConfig(configId, patch),
    onSuccess: invalidate,
  })
}

export function useDeleteGptDigestConfigMutation() {
  const invalidate = useInvalidateGptDigest()
  return useMutation({
    mutationFn: (configId: number) => deleteGptDigestConfig(configId),
    onSuccess: invalidate,
  })
}

export function useConfigFeed(configId: number | null) {
  return useQuery({
    queryKey: ['gpt-digest', 'feed', configId],
    queryFn: () => getConfigFeed(configId as number),
    enabled: configId !== null,
  })
}

export function useConfigPreviewMutation() {
  return useMutation({
    mutationFn: (input: { configId: number; putBack?: string[] }) =>
      previewConfigDigest(input.configId, input.putBack),
  })
}

export function useGenerateConfigMutation() {
  const invalidate = useInvalidateGptDigest()
  return useMutation({
    mutationFn: (input: { configId: number; putBack?: string[] }) =>
      generateConfigDigest(input.configId, input.putBack),
    onSuccess: invalidate,
  })
}

export function useConfigIssues(configId: number | null) {
  return useQuery({
    queryKey: ['gpt-digest', 'issues', configId],
    queryFn: ({ signal }) => listConfigIssues(configId as number, signal),
    enabled: configId !== null,
  })
}

/** F28：期内事实对照（按需，不落库）。 */
export function useCompareFactsMutation() {
  return useMutation({
    mutationFn: (vars: { configId: number; issueKey: string }) =>
      compareFactsGptDigestIssue(vars.configId, vars.issueKey),
  })
}

/** F07：相邻对照。 */
export function useCompareGptDigestIssueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { configId: number; issueKey: string }) =>
      compareGptDigestIssue(vars.configId, vars.issueKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
  })
}

/** F03：生成周报。 */
export function useWeeklyDigestMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (configId: number) => generateWeeklyDigest(configId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
  })
}

/** F23：按需标题翻译（一次一条；缓存以服务端为准）。 */
export function useTitleTranslationMutation() {
  return useMutation({
    mutationFn: (vars: { entryRef: string }) => translateEntryTitle(vars.entryRef),
  })
}

/** F11/F13/F001：设置来源显示覆盖（隐藏期/阅读起点/新鲜度预警阈值）。 */
export function useSetSourceOverrideMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: {
      feedUrl: string
      hiddenUntil?: string | null
      showFrom?: string | null
      staleAlertHours?: number | null
      language?: string | null
      unreadAlertThreshold?: number | null
      syncPriority?: number | null
    }) => setSourceOverride(patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['entries'] })
      await queryClient.invalidateQueries({ queryKey: ['stale-sources'] })
      await queryClient.invalidateQueries({ queryKey: ['sources-volume'] })
    },
  })
}

/** F001：超期来源列表（面板打开时才拉取）。 */
export function useStaleSourcesQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['stale-sources'],
    queryFn: ({ signal }) => fetchStaleSources(signal),
    enabled,
  })
}

/** F004：重复订阅候选（面板打开时才拉取）。 */
export function useDuplicateSuspectsQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['duplicate-suspects'],
    queryFn: ({ signal }) => fetchDuplicateSuspects(signal),
    enabled,
  })
}

/** F005：单订阅备注（对话框打开时拉取）。 */
export function useSourceNotesQuery(subscriptionRef: string | null) {
  return useQuery({
    queryKey: ['source-notes', subscriptionRef],
    queryFn: ({ signal }) => getSourceNotes(subscriptionRef as string, signal),
    enabled: subscriptionRef !== null,
  })
}

/** F005：备注列表（可选关键词过滤）。 */
export function useSourceNotesListQuery(noteSearch: string | null) {
  return useQuery({
    queryKey: ['source-notes-list', noteSearch],
    queryFn: ({ signal }) => listSourceNotes(noteSearch ?? undefined, signal),
    enabled: noteSearch !== null,
  })
}

/** F005：保存备注（成功后失效备注缓存）。 */
export function useUpdateSourceNotesMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      subscriptionRef: string
      note?: string | null
      reason?: string | null
      maintenanceLog?: string | null
    }) => {
      const { subscriptionRef, ...body } = vars
      return updateSourceNotes({ subscriptionRef, ...body })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['source-notes'] })
      await queryClient.invalidateQueries({ queryKey: ['source-notes-list'] })
    },
  })
}

/** F006：批量分类迁移（成功后失效订阅相关 server state）。 */
export function useBatchMoveMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { refs: string[]; targetCategoryId: string }) =>
      batchMoveSubscriptions(vars),
    onSuccess: async () => {
      invalidateSubscriptionState(queryClient)
    },
  })
}

/** F29：引用某文章的书签/笔记（文章页反向入口；空 = 没有笔记引用）。 */
export function useNotesByEntry(entryRef: string | null) {
  return useQuery({
    queryKey: ['library', 'notes-by-entry', entryRef],
    queryFn: ({ signal }) => listNotesByEntry(entryRef as string, signal),
    enabled: entryRef !== null,
  })
}

/** F19：延后稍后读项目——成功后失效时间线（行即从列表消失）。 */
export function useSnoozeReadLaterMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { itemRef: string; days: number }) => {
      const until = new Date(Date.now() + vars.days * 86_400_000).toISOString()
      return snoozeReadLaterItem(vars.itemRef, until)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspace', 'read-later'] })
      await queryClient.invalidateQueries({ queryKey: READ_LATER_TIMELINE_KEY })
    },
  })
}

/** F08：人工修订某期（重渲染 + updated 前移；entry id 不变）。 */
export function useReviseGptDigestIssueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      configId: number
      issueKey: string
      payload: GptDigestIssueRevise
    }) => reviseGptDigestIssue(vars.configId, vars.issueKey, vars.payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
  })
}

/** N172：仅重跑润色阶段（选材/总结成果保留；meta.polishFailed 清除）。 */
export function useRetryPolishGptDigestIssueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { configId: number; issueKey: string }) =>
      retryPolishGptDigestIssue(vars.configId, vars.issueKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
  })
}

/** N175：裁剪预览（issue 面板按需开启；零写入、零模型调用）。 */
export function useDigestTrimPreviewQuery(configId: number, issueKey: string, enabled: boolean) {
  return useQuery({
    queryKey: ['gpt-digest', 'trim-preview', configId, issueKey],
    queryFn: ({ signal }) => getDigestTrimPreview(configId, issueKey, signal),
    enabled,
  })
}

/** F05：生成初学者解释版（独立条目，原版不变）。 */
export function useExplainGptDigestIssueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { configId: number; issueKey: string }) =>
      explainGptDigestIssue(vars.configId, vars.issueKey),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['gpt-digest'] })
    },
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

// ---- P16：多设备交接（设备档案 / 导出模板；用户级数据） ----

/** 设备档案列表（URI 生成的唯一设备信息来源）。 */
export function useObsidianDevices() {
  return useQuery({
    queryKey: ['obsidian', 'devices'],
    queryFn: ({ signal }) => listObsidianDevices(signal),
  })
}

function useInvalidateObsidianDevices() {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['obsidian', 'devices'] })
  }
}

export function useCreateObsidianDeviceMutation() {
  const invalidate = useInvalidateObsidianDevices()
  return useMutation({
    mutationFn: (payload: ObsidianDeviceProfilePayload) => createObsidianDevice(payload),
    onSuccess: invalidate,
  })
}

export function useUpdateObsidianDeviceMutation() {
  const invalidate = useInvalidateObsidianDevices()
  return useMutation({
    mutationFn: (vars: { deviceId: string; payload: ObsidianDeviceProfilePayload }) =>
      updateObsidianDevice(vars.deviceId, vars.payload),
    onSuccess: invalidate,
  })
}

export function useDeleteObsidianDeviceMutation() {
  const invalidate = useInvalidateObsidianDevices()
  return useMutation({
    mutationFn: (deviceId: string) => deleteObsidianDevice(deviceId),
    onSuccess: invalidate,
  })
}

/** 导出模板（template='' 表示跟随默认模板）。 */
export function useObsidianExportTemplate() {
  return useQuery({
    queryKey: ['obsidian', 'export-template'],
    queryFn: ({ signal }) => getObsidianExportTemplate(signal),
  })
}

export function useUpdateObsidianExportTemplateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      template: string | null
      exportNamePolicy?: ObsidianExportTemplateView['exportNamePolicy']
    }) =>
      // 位置参数契约保持：未带策略时不传第二参（既有调用方断言兼容）。
      vars.exportNamePolicy !== undefined
        ? updateObsidianExportTemplate(vars.template, vars.exportNamePolicy)
        : updateObsidianExportTemplate(vars.template),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obsidian', 'export-template'] })
    },
  })
}

/** 模板预览（编辑器防抖调用；unknownVars 由 UI 诚实列出）。 */
export function useObsidianTemplatePreviewMutation() {
  return useMutation({
    mutationFn: (vars: { template: string; entryRef?: string | null }) =>
      previewObsidianExportTemplate(vars.template, vars.entryRef),
  })
}

/** 导出到 Obsidian 交接（uri / file 裁决在服务端）。 */
export function useObsidianExportHandoffMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { entryRef: string; deviceId: string; onlySinceLastExport?: boolean }) =>
      requestObsidianExportHandoff(vars.entryRef, vars.deviceId, {
        onlySinceLastExport: vars.onlySinceLastExport,
      }),
    onSuccess: async () => {
      // N137：交接成功即回标导出水位 → 失效增量预览。
      await queryClient.invalidateQueries({ queryKey: ['annotations', 'export-delta'] })
    },
  })
}

/** N139 导出侧链接校验（只读；交接前由导出对话框调用）。 */
export function useObsidianExportValidateMutation() {
  return useMutation({
    mutationFn: (vars: { entryRef: string; deviceId: string; onlySinceLastExport?: boolean }) =>
      validateObsidianExport(vars.entryRef, vars.deviceId, {
        onlySinceLastExport: vars.onlySinceLastExport,
      }),
  })
}

/** N140 交接记录列表（新→旧；confirmed 只能由显式确认产生）。 */
export function useObsidianHandoffLog() {
  return useQuery({
    queryKey: ['obsidian', 'handoff-log'],
    queryFn: ({ signal }) => listObsidianHandoffLog(signal),
  })
}

/** N140 显式确认（幂等；不存在 → 错误由 UI 透出）。 */
export function useConfirmObsidianHandoffMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (handoffId: string) => confirmObsidianHandoff(handoffId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obsidian', 'handoff-log'] })
    },
  })
}

/** N140 清空交接历史。 */
export function useClearObsidianHandoffLogMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => clearObsidianHandoffLog(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['obsidian', 'handoff-log'] })
    },
  })
}

/** N137 增量预览（可选按文章收窄；供导出对话框展示新增/修改）。 */
export function useAnnotationsExportDelta(entryRef: string | null) {
  return useQuery({
    queryKey: ['annotations', 'export-delta', { entryRef }],
    queryFn: ({ signal }) => getAnnotationsExportDelta(entryRef, signal),
    enabled: entryRef !== null,
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
  createAgentRecipe,
  createAgentThread,
  decideAgentApproval,
  deleteAgentRecipe,
  deleteAgentThread,
  getGraph,
  listAgentMessages,
  listAgentRecipes,
  listAgentThreads,
  listTags,
  pauseAgentThread,
  resumeAgentThread,
  retryAgentThread,
  reviseAgentApproval,
  runAgentRecipe,
  sendAgentMessage,
  undoAgentStep,
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

/** P0-10：给条目绑定标签（POST 幂等由 BFF 承载；失效条目标签 + 全列表
 * + 图谱——Q-P2-40：图谱是标签绑定的派生视图，rename/delete 失效了它
 * 而 assign/unassign 漏了，同一派生链两套标准）。 */
export function useAssignTagMutation(itemRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => assignTag({ itemRef, name, origin: 'manual' }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['item-tags', itemRef] }),
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
        queryClient.invalidateQueries({ queryKey: ['graph'] }),
      ])
    },
  })
}

/** P0-10：解绑标签（DELETE；失效条目标签 + 全列表 + 图谱，同 Q-P2-40）。 */
export function useUnassignTagMutation(itemRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => unassignTag({ itemRef, name, origin: 'manual' }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['item-tags', itemRef] }),
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
        queryClient.invalidateQueries({ queryKey: ['graph'] }),
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

/** pool #16：合并预览（受影响计数；仅选定源+目标后启用）。 */
export function useTagMergePreview(sourceId: number | null, targetId: number | null) {
  return useQuery({
    queryKey: ['tag-merge-preview', { sourceId, targetId }],
    queryFn: ({ signal }) => getTagMergePreview(sourceId!, targetId!, signal),
    enabled: sourceId !== null && targetId !== null && sourceId !== targetId,
    staleTime: 0,
  })
}

/** pool #16：执行合并（源并入目标；tags/graph/条目标签全部失效）。 */
export function useTagMergeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { sourceId: number; targetId: number }) =>
      mergeTags(vars.sourceId, vars.targetId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tags'] }),
        queryClient.invalidateQueries({ queryKey: ['graph'] }),
        queryClient.invalidateQueries({ queryKey: ['item-tags'] }),
      ])
    },
  })
}

/** N150：撤销最近一次合并（重建源标签并恢复绑定；同样全量失效）。 */
export function useTagMergeUndoMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => undoTagMerge(),
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

// ---- RAG（状态 chip + 设置页操作入口：启用开关 / 重建按钮均消费本节） ----

export function useRagStatus(enabled: boolean = true) {
  return useQuery({
    queryKey: ['rag', 'status'],
    queryFn: ({ signal }) => getRagStatus(signal),
    enabled,
  })
}

/** P0-07：显式启用语义索引（用户授权下载/加载模型）。成功后失效状态
 * （enabled / chunks 随 enable 的 warmup 结果刷新；lastError 原样透出
 * 给调用方展示）。 */
export function useEnableRagMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => enableRag(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rag'] })
    },
  })
}

/** P0-07：全量重建索引（有界长任务；成功后失效状态——chunks /
 * lastRebuildAt 刷新）。RagRebuildBusy（重建进行中）的 message 原样透出。 */
export function useRebuildRagMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => rebuildRag(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rag'] })
    },
  })
}

// ---- P0-02：统一 resolve（引用 → 卡片视图；批量一次往返） ----

/** 批量解析 refs（引用来自 agent citations 等聚合场景；空数组不发请求）。
 * stale/unknown 目标由服务端降级为 stale 行，本 hook 永不因单个失效 ref
 * 失败。 */
export function useResolveRefs(refs: string[]) {
  const key = [...refs].sort().join('\n')
  return useQuery({
    queryKey: ['resolve', key],
    queryFn: async ({ signal }) => {
      // Q-P2-14：调用方（收件箱长列表）一次传整页 refs；端点单次上限
      // 100，超限分块并发解析后拍平（此前 >100 refs 会整请求 400）。
      const unique = [...new Set(refs)]
      if (unique.length <= 100) return resolveItems(unique, signal)
      const chunks: string[][] = []
      for (let i = 0; i < unique.length; i += 100) {
        chunks.push(unique.slice(i, i + 100))
      }
      const results = await Promise.all(
        chunks.map((chunk) => resolveItems(chunk, signal)),
      )
      return { items: results.flatMap((result) => result.items) }
    },
    enabled: refs.length > 0,
    staleTime: 30_000,
    retry: false,
  })
}

// ---- 0021：Inbox 推送来源（连接器 + 条目 refs；卡片复用 /resolve） ----

/** 收件连接器列表（服务端永不回显 secret）。 */
export function useInboxSources() {
  return useQuery({
    queryKey: ['inbox', 'sources'],
    queryFn: ({ signal }) => listInboxSources(signal),
    refetchOnWindowFocus: true,
  })
}

/** 新建连接器；成功后失效连接器列表与统一来源注册表。 */
export function useCreateInboxSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => createInboxSource(name),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['inbox', 'sources'] }),
        queryClient.invalidateQueries({ queryKey: ['sources'] }),
      ])
    },
  })
}

/** 删除连接器（连带其全部推送条目）；失效收件与注册表视图。 */
export function useDeleteInboxSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceUuid: string) => deleteInboxSource(sourceUuid),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['inbox'] }),
        queryClient.invalidateQueries({ queryKey: ['sources'] }),
      ])
    },
  })
}

/** 收件条目 refs 分页（最新在前；cursor opaque）。 */
export function useInboxItems() {
  return useInfiniteQuery({
    queryKey: ['inbox', 'items'],
    queryFn: ({ pageParam, signal }) =>
      listInboxItems({ cursor: pageParam, limit: 20 }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    // Q-P2-41：与 entries/read-later 一致的病态增长内存保险丝——
    // 收件箱持续推送 + 长滚动时缓存页数不设上界会无限膨胀。
    maxPages: 50,
    // fresh-eyes Issue 2：推送型视图对「切回标签页」敏感——全局默认
    // 已关 focus 刷新，这里显式恢复，否则挂载期间没有刷新路径。
    // 取舍（终审 Issue 4）：v5 的 infinite refetch 会按 pageParam 重拉
    // 全部缓存页（maxPages 封顶）；推送型收件箱优先正确性。
    refetchOnWindowFocus: true,
  })
}

/** 删除单条推送内容；失效收件条目与解析卡片。 */
export function useDeleteInboxItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemRef: string) => deleteInboxItem(itemRef),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['inbox'] }),
        queryClient.invalidateQueries({ queryKey: ['resolve'] }),
      ])
    },
  })
}

// ---- Q-P1-06：统一来源注册表（GET /api/v1/sources 的首批真实消费者） ----

/** 只读来源注册表：请求时由各 owning store 投影（统一 API ≠ 统一库），
 * 健康面（lastError/lastSuccessAt）由 owning store 维护。 */
export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: ({ signal }) => listSources(signal),
    staleTime: 30_000,
  })
}

// ---- Q-P1-07：IMAP 收信（后端 4 端点的首批 UI 消费者） ----

export function useMailImapSettings() {
  return useQuery({
    queryKey: ['mail', 'imap'],
    queryFn: ({ signal }) => getMailImapSettings(signal),
  })
}

export function useUpdateMailImapSettingsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: MailImapSettingsUpdate) => updateMailImapSettings(patch),
    onSuccess: (server) => {
      // 用响应直接写缓存（GET 语义返回值）；密码框保持空（write-only）。
      queryClient.setQueryData(['mail', 'imap'], server)
    },
  })
}

export function useTestMailImapMutation() {
  return useMutation({ mutationFn: () => testMailImap() })
}

export function usePollMailImapMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => pollMailImap(),
    onSuccess: () => {
      // 拉取产生新的 bridge 条目 → 列表与摘要视图同步。
      void queryClient.invalidateQueries({ queryKey: ['mail'] })
    },
  })
}

// ==== W2（F021–F040）净新增 hooks ===========================================

// ---- F021 手工关联内容 ----

export function useItemRelations(itemRef: string | null | undefined) {
  return useQuery({
    queryKey: ['item-relations', itemRef],
    queryFn: ({ signal }) => listRelationsForItem(itemRef as string, signal),
    enabled: Boolean(itemRef),
  })
}

export function useCreateRelationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createRelation,
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['item-relations', variables.srcRef] })
      void queryClient.invalidateQueries({ queryKey: ['item-relations', variables.dstRef] })
    },
  })
}

export function useDeleteRelationMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteRelation,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['item-relations'] })
    },
  })
}

// ---- F022 收件箱归类规则 ----

export function useInboxRules() {
  return useQuery({ queryKey: ['inbox-rules'], queryFn: ({ signal }) => getInboxRules(signal) })
}

export function useInboxRuleMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['inbox-rules'] })
  const create = useMutation({ mutationFn: createInboxRule, onSuccess: invalidate })
  const patch = useMutation({
    mutationFn: (input: { id: number; body: Parameters<typeof patchInboxRule>[1] }) =>
      patchInboxRule(input.id, input.body),
    onSuccess: invalidate,
  })
  const move = useMutation({
    mutationFn: (input: { id: number; direction: 'up' | 'down' }) => moveInboxRule(input.id, input.direction),
    onSuccess: invalidate,
  })
  const remove = useMutation({ mutationFn: deleteInboxRule, onSuccess: invalidate })
  return { create, patch, move, remove }
}

// ---- F023 跨来源作者聚合 ----

export function useAuthors() {
  return useQuery({ queryKey: ['authors'], queryFn: ({ signal }) => getAuthors(signal) })
}

export function useAuthorItems(author: string | null) {
  return useQuery({
    queryKey: ['author-items', author],
    queryFn: ({ signal }) => getAuthorItems(author as string, 0, 20, signal),
    enabled: Boolean(author),
  })
}

export function useAuthorAliases() {
  return useQuery({
    queryKey: ['author-aliases'],
    queryFn: ({ signal }) => getAuthorAliases(signal),
  })
}

export function useAuthorAliasMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['authors'] })
    void queryClient.invalidateQueries({ queryKey: ['author-aliases'] })
    void queryClient.invalidateQueries({ queryKey: ['author-items'] })
  }
  const create = useMutation({ mutationFn: createAuthorAlias, onSuccess: invalidate })
  const remove = useMutation({ mutationFn: deleteAuthorAlias, onSuccess: invalidate })
  return { create, remove }
}

// ---- F024 积压整理助手 ----

export function useBacklogMutations() {
  const queryClient = useQueryClient()
  return {
    preview: useMutation({
      mutationFn: (condition: BacklogCondition) => previewBacklog(condition),
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ['entries'] })
      },
    }),
    apply: useMutation({
      mutationFn: (input: { condition: BacklogCondition; token: string }) =>
        applyBacklog(input.condition, input.token),
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: ['entries'] })
        void queryClient.invalidateQueries({ queryKey: ['search'] })
      },
    }),
  }
}

// ---- F025/F027：范围生成 + 版本切换 ----

export function useGenerateSummaryScopedMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (maxChars: number | undefined) =>
      generateEntrySummaryScoped(entryRef, maxChars),
    onSuccess: (data) => {
      queryClient.setQueryData(['entry-summary', entryRef], data)
    },
  })
}

export function useActivateSummaryVersionMutation(entryRef: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (versionId: string) => activateSummaryVersion(entryRef, versionId),
    onSuccess: (data) => {
      queryClient.setQueryData(['entry-summary', entryRef], data)
    },
  })
}

// ---- F030 问答模板 ----

export function useQaTemplates() {
  return useQuery({
    queryKey: ['qa-templates'],
    queryFn: ({ signal }) => getQaTemplates(signal),
  })
}

export function useQaTemplateMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['qa-templates'] })
  return {
    create: useMutation({ mutationFn: createQaTemplate, onSuccess: invalidate }),
    patch: useMutation({
      mutationFn: (input: { id: string; body: { name: string; text?: string } }) =>
        patchQaTemplate(input.id, input.body),
      onSuccess: invalidate,
    }),
    remove: useMutation({ mutationFn: deleteQaTemplate, onSuccess: invalidate }),
  }
}

// ---- F029 术语命中预览 ----

export function useGlossaryHits(
  entryRef: string,
  enabled: boolean,
  blocks?: TranslationSegmentBlockInput[] | null,
) {
  // N083：提供 blocks 时逐块定位（命中附带 blockIndexes）；blocks 参与
  // 缓存键（同一篇的不同块集合各自定位）。
  const blocksKey = blocks && blocks.length > 0 ? JSON.stringify(blocks) : ''
  return useQuery({
    queryKey: ['glossary-hits', entryRef, blocksKey],
    queryFn: ({ signal }) =>
      getGlossaryHits(entryRef, {
        blocks: blocksKey ? (blocks as TranslationSegmentBlockInput[]) : undefined,
        signal,
      }),
    enabled,
  })
}

// ---- F031/F032 日报草稿审阅 + 缺失日期补刊 ----

export function usePublishGptDigestIssueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { configId: number; issueKey: string }) =>
      publishGptDigestIssue(input.configId, input.issueKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gpt-digest-issues'] })
    },
  })
}

export function useMissingDigestDates(configId: number) {
  return useQuery({
    queryKey: ['gpt-digest-missing', configId],
    queryFn: ({ signal }) => getMissingDigestDates(configId, signal),
  })
}

export function useGenerateDigestForDateMutation(configId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (targetDate: string) => generateDigestForDate(configId, targetDate),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['gpt-digest-issues'] })
      void queryClient.invalidateQueries({ queryKey: ['gpt-digest-missing', configId] })
    },
  })
}

// ---- F038/F039/F035 hooks ----

export function useAuthSessions() {
  return useQuery({ queryKey: ['auth-sessions'], queryFn: ({ signal }) => listAuthSessions(signal) })
}

export function useRevokeSessionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeAuthSession,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-sessions'] }),
  })
}

// ---- N006 通行密钥 / N007 两步验证（账户安全面） ----

export function usePasskeys() {
  return useQuery({ queryKey: ['auth-passkeys'], queryFn: ({ signal }) => listPasskeys(signal) })
}

export function useRegisterPasskeyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { label: string; challenge: string; credential: Record<string, unknown> }) =>
      finishPasskeyRegistration(input),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-passkeys'] }),
  })
}

export function useDeletePasskeyMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { credentialId: string; currentPassword: string; totpCode?: string }) =>
      deletePasskey(input.credentialId, input.currentPassword, input.totpCode),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-passkeys'] }),
  })
}

export function useTotpStatus() {
  return useQuery({ queryKey: ['auth-totp'], queryFn: ({ signal }) => getTotpStatus(signal) })
}

export function useTotpSetupMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: setupTotp,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-totp'] }),
  })
}

export function useTotpEnableMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (code: string) => enableTotp(code),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-totp'] }),
  })
}

export function useTotpDisableMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { code: string; currentPassword: string }) => disableTotp(input.code, input.currentPassword),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['auth-totp'] }),
  })
}

export function useDiagnostics() {
  return useQuery({ queryKey: ['diagnostics'], queryFn: ({ signal }) => getDiagnostics(signal) })
}

export function usePinnedViews() {
  return useQuery({ queryKey: ['pinned-views'], queryFn: ({ signal }) => getPinnedViews(signal) })
}

export function usePinnedViewCount(id: string | null) {
  return useQuery({
    queryKey: ['pinned-view-count', id],
    queryFn: ({ signal }) => getPinnedViewCount(id as string, signal),
    enabled: Boolean(id),
  })
}

export function usePinMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['pinned-views'] })
    void queryClient.invalidateQueries({ queryKey: ['saved-views'] })
  }
  return {
    pin: useMutation({ mutationFn: pinSavedView, onSuccess: invalidate }),
    unpin: useMutation({ mutationFn: unpinSavedView, onSuccess: invalidate }),
  }
}

// ==== W6（F101–F115）=========================================================

// ---- F101/F102：日报素材池 ----

/** 素材池列表（待用按 position 升序；used 分列）。 */
export function useDigestPool(configId: number) {
  return useQuery({
    queryKey: ['gpt-digest', 'pool', configId],
    queryFn: ({ signal }) => listDigestPool(configId, signal),
  })
}

function invalidateDigestPool(queryClient: ReturnType<typeof useQueryClient>, configId: number) {
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['gpt-digest', 'pool', configId] }),
      queryClient.invalidateQueries({ queryKey: ['gpt-digest', 'configs'] }),
    ])
  }
}

export function useAddDigestPoolEntryMutation(configId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entryRef: string) => addDigestPoolEntry(configId, entryRef),
    onSuccess: invalidateDigestPool(queryClient, configId),
  })
}

export function useRemoveDigestPoolEntryMutation(configId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entryId: number) => removeDigestPoolEntry(configId, entryId),
    onSuccess: invalidateDigestPool(queryClient, configId),
  })
}

export function useReorderDigestPoolMutation(configId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (orderedIds: number[]) => reorderDigestPool(configId, orderedIds),
    onSuccess: invalidateDigestPool(queryClient, configId),
  })
}

// ---- F103：订阅 token 轮换两步（dry-run → 执行） ----

export function useRotateGptDigestDryRunMutation() {
  return useMutation({ mutationFn: () => rotateGptDigestFeedDryRun() })
}

// ---- F104/F110：邮件解析对照 / 会话（按需拉取，不预热） ----

export function useMailParseDebugMutation() {
  return useMutation({
    mutationFn: (input: { listUuid: string; messageId: string }) =>
      getMailParseDebug(input.listUuid, input.messageId),
  })
}

export function useMailThreadMutation() {
  return useMutation({
    mutationFn: (input: { listUuid: string; messageId: string }) =>
      getMailThread(input.listUuid, input.messageId),
  })
}

// ---- F105：邮件接收规则 ----

export function useMailRules(listUuid: string | null | undefined) {
  return useQuery({
    queryKey: ['mail', 'rules', listUuid ?? ''],
    queryFn: ({ signal }) => listMailRules(listUuid as string, signal),
    enabled: typeof listUuid === 'string' && listUuid !== '',
  })
}

function invalidateMailRules(queryClient: ReturnType<typeof useQueryClient>, listUuid: string) {
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['mail', 'rules', listUuid] })
  }
}

export function useCreateMailRuleMutation(listUuid: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: MailRuleCreateInput) => createMailRule(listUuid, input),
    onSuccess: invalidateMailRules(queryClient, listUuid),
  })
}

export function usePatchMailRuleMutation(listUuid: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ruleId: number; patch: { enabled?: boolean; value?: string; action?: string } }) =>
      patchMailRule(input.ruleId, input.patch),
    onSuccess: invalidateMailRules(queryClient, listUuid),
  })
}

export function useMoveMailRuleMutation(listUuid: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { ruleId: number; direction: 'up' | 'down' }) =>
      moveMailRule(input.ruleId, input.direction),
    onSuccess: invalidateMailRules(queryClient, listUuid),
  })
}

export function useDeleteMailRuleMutation(listUuid: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: number) => deleteMailRule(ruleId),
    onSuccess: invalidateMailRules(queryClient, listUuid),
  })
}

export function useDryRunMailRuleMutation(listUuid: string) {
  return useMutation({
    mutationFn: (sample: { field: 'from' | 'subject'; value: string }) =>
      dryRunMailRule(listUuid, sample),
  })
}

// ---- F106：IMAP 历史回填（dry-run → 执行） ----

export function useMailBackfillMutation() {
  return useMutation({ mutationFn: (body: { since?: string; uids?: number[]; dryRun: boolean }) => backfillMailImap(body) })
}

// ---- F107：收件投递事件 / 重放 ----

export function useInboxEvents(sourceUuid: string | null | undefined) {
  return useQuery({
    queryKey: ['inbox', 'events', sourceUuid ?? ''],
    queryFn: ({ signal }) => listInboxEvents(sourceUuid as string, signal),
    enabled: typeof sourceUuid === 'string' && sourceUuid !== '',
  })
}

export function useReplayInboxEventMutation(sourceUuid: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (eventId: number) => replayInboxEvent(eventId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['inbox', 'events', sourceUuid] }),
        queryClient.invalidateQueries({ queryKey: ['inbox', 'items'] }),
      ])
    },
  })
}

// ---- F108：接入检查（零写入试跑；按需触发不进缓存） ----

export function useIngestDryRunMutation(sourceUuid: string) {
  return useMutation({
    mutationFn: (payloadJson: string) => dryRunInboxIngest(sourceUuid, payloadJson),
  })
}

// ---- F109：收件连接器凭据轮换（一次性 secret，同创建语义） ----

export function useRotateInboxSourceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (uuid: string) => rotateInboxSource(uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['inbox', 'sources'] })
    },
  })
}

// ---- F114：存储保留策略 ----

export function useStorageRetention() {
  return useQuery({
    queryKey: ['storage', 'retention'],
    queryFn: ({ signal }) => getStorageRetention(signal),
  })
}

export function useSaveStorageRetentionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: { enabled?: boolean; aiVersionsDays?: number | null; taskLogDays?: number | null }) =>
      putStorageRetention(values),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['storage', 'retention'] })
    },
  })
}

export function useRetentionPreviewMutation() {
  return useMutation({ mutationFn: () => previewStorageRetention() })
}

export function useRetentionApplyMutation() {
  return useMutation({ mutationFn: () => applyStorageRetention() })
}

/** N188：数据保留到期提醒（只读）。 */
export function useRetentionNotice() {
  return useQuery({
    queryKey: ['storage', 'retention', 'notice'],
    queryFn: ({ signal }) => getRetentionNotice(signal),
  })
}

export function useRetentionPostponeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (days: number) => postponeRetention(days),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['storage', 'retention', 'notice'] })
    },
  })
}

// ---- N041/N042/N043/N044 今日必读队列 ----

const QUEUE_TODAY_KEY = ['queue', 'today']
const QUEUE_SNAPSHOTS_KEY = ['queue', 'snapshots']

/** 今日队列（pending + done；removed 行不出库门）。 */
export function useTodayQueue(enabled = true) {
  return useQuery({
    queryKey: QUEUE_TODAY_KEY,
    queryFn: ({ signal }) => getTodayQueue(signal),
    enabled,
  })
}

/** 生成（或幂等返回）。已存在的队列绝不被重排（generated=false）。 */
export function useGenerateQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      timeBudgetMinutes?: number
      levels?: string[]
      workspaceId?: string
      force?: boolean
    }) => generateTodayQueue(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 手动加入（itemRef；可选段名）。 */
export function useAddQueueItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { itemRef: string; segment?: string | null }) =>
      addQueueItem(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 移除（status=removed，行保留）。 */
export function useRemoveQueueItemMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (itemId: string) => removeQueueItem(itemId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 完成状态（set 语义；完成按条目身份记账在服务端）。 */
export function useQueueItemDoneMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { itemId: string; done: boolean }) =>
      setQueueItemDone(input.itemId, input.done),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 持久化重排。 */
export function useReorderQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (order: string[]) => reorderTodayQueue(order),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 行菜单移动分段。 */
export function useMoveQueueItemSegmentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { itemId: string; segment: string | null }) =>
      moveQueueItemSegment(input.itemId, input.segment),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 段顺序（服务端存储 → 跨设备一致）。 */
export function useQueueSegmentOrderMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (order: string[]) => setQueueSegmentOrder(order),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_TODAY_KEY })
    },
  })
}

/** 冻结当前 pending 成员为不可变快照。 */
export function useFreezeQueueMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (label: string) => freezeTodayQueue(label),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_SNAPSHOTS_KEY })
    },
  })
}

/** 快照列表（新→旧）。 */
export function useQueueSnapshots(enabled = true) {
  return useQuery({
    queryKey: QUEUE_SNAPSHOTS_KEY,
    queryFn: ({ signal }) => getQueueSnapshots(signal),
    enabled,
  })
}

/** 打开冻结视图（原始成员顺序；消失 ref 呈现占位）。 */
export function useQueueSnapshot(snapshotId: string | null) {
  return useQuery({
    queryKey: ['queue', 'snapshot', snapshotId],
    queryFn: ({ signal }) => getQueueSnapshot(snapshotId as string, signal),
    enabled: snapshotId !== null,
  })
}

/** 删除快照。 */
export function useDeleteQueueSnapshotMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (snapshotId: string) => deleteQueueSnapshot(snapshotId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: QUEUE_SNAPSHOTS_KEY })
    },
  })
}

// ---- intake 批次：N121 批量粘贴 / N122 剪藏锁定候选 / N123 清理预览 / 邮件详情 ----
// 本节 client 函数按段引入（本文件约定 APPEND-ONLY，新增 import 只能
// 随新节追加在尾部；ESM 顶层 import 提升，行为等价）。

import {
  applyClipCandidate,
  bulkLinks,
  discardClipCandidate,
  getClipCandidate,
  getMailMessageDetail,
  listMailMessages,
  previewClipCleanup,
  refreshClip,
  setClipLock,
} from './client'
import type { ClipCandidate, MailMessageDetail } from './client'

/** N121：批量粘贴（逐条 created/duplicate/failed；成功后失效书签与剪藏）。 */
export function useBulkLinksMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { urls: string[]; target: 'bookmark' | 'clip' }) =>
      bulkLinks(vars.urls, vars.target),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library'] })
    },
  })
}

/** N122：锁定/解锁（覆盖式写入的唯一开关；成功后失效剪藏 detail）。 */
export function useClipLockMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { clipRef: string; locked: boolean }) =>
      setClipLock(vars.clipRef, vars.locked),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

/** N122：刷新（未锁定 → 应用；锁定 → 候选）。 */
export function useClipRefreshMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (clipRef: string) => refreshClip(clipRef),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

/** N122：查看候选（Dialog 打开时才发请求）。 */
export function useClipCandidate(clipRef: string | null) {
  return useQuery({
    queryKey: ['library', 'clips', 'candidate', clipRef],
    queryFn: ({ signal }) => getClipCandidate(clipRef!, signal),
    enabled: clipRef !== null,
  })
}

export type { ClipCandidate }

/** N122：应用候选（可带 keepIds 走同一净化管线）。 */
export function useApplyClipCandidateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { clipRef: string; keepIds?: string[] }) =>
      applyClipCandidate(vars.clipRef, vars.keepIds),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

/** N122：丢弃候选。 */
export function useDiscardClipCandidateMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (clipRef: string) => discardClipCandidate(clipRef),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
    },
  })
}

/** N123：清理预览（零写入；逐块建议可改）。 */
export function useClipCleanupPreviewMutation() {
  return useMutation({
    mutationFn: (html: string) => previewClipCleanup(html),
  })
}

/** N125/126/127：邮件消息清单（每列表有界 ≤50）。 */
export function useMailMessages(listUuid: string | null) {
  return useQuery({
    queryKey: ['mail', 'messages', listUuid],
    queryFn: ({ signal }) => listMailMessages(listUuid!, signal),
    enabled: listUuid !== null,
  })
}

export type { MailMessageDetail }

/** N125/126/127：邮件详情（附件 / 双正文形态 / 被阻止媒体 / 身份提示）。 */
export function useMailMessageDetail(listUuid: string | null, messageId: string | null) {
  return useQuery({
    queryKey: ['mail', 'message-detail', listUuid, messageId],
    queryFn: ({ signal }) => getMailMessageDetail(listUuid!, messageId!, signal),
    enabled: listUuid !== null && messageId !== null,
  })
}

// ---- N164–N170 Agent ops（暂停续接 / 批准修订 / 步骤重试 / 差异撤销 / 配方）----

/** N164：暂停运行中的回合（在工具间检查点冻结）。 */
export function useAgentPauseMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => pauseAgentThread(threadId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** N164：续接暂停的回合（已执行步骤绝不重复；过期批准 → 重新确认）。 */
export function useAgentResumeMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => resumeAgentThread(threadId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** N167：批准前修订参数（旧批准作废，产生新批准行）。 */
export function useAgentReviseApprovalMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: { approvalId: string; newArgs: Record<string, unknown> }) =>
      reviseAgentApproval(threadId, vars.approvalId, vars.newArgs),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** N168：失败步骤单独重试（可能产生新的写批准）。 */
export function useAgentRetryMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => retryAgentThread(threadId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** N169：按 stepId 差异撤销一次写副作用。 */
export function useAgentUndoMutation(threadId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (stepId: string) => undoAgentStep(threadId, stepId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'messages', threadId] })
    },
  })
}

/** N170：配方列表。 */
export function useAgentRecipes() {
  return useQuery({
    queryKey: ['agent', 'recipes'],
    queryFn: ({ signal }) => listAgentRecipes(signal),
  })
}

export function useCreateAgentRecipeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      name: string
      input: string
      toolWhitelist: string[]
      scope?: Record<string, unknown> | null
    }) => createAgentRecipe(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'recipes'] })
    },
  })
}

export function useDeleteAgentRecipeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (recipeId: string) => deleteAgentRecipe(recipeId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'recipes'] })
    },
  })
}

/** N170：运行配方 = 创建新会话并以配方输入开启第一回合。 */
export function useRunAgentRecipeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (recipeId: string) => runAgentRecipe(recipeId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['agent', 'threads'] })
    },
  })
}
