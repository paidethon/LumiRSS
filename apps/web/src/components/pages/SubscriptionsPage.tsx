/** SubscriptionsPage — 订阅中心（0011 Gate 4 → 0013 Gate 3 演进）。
 *
 * 0013 Gate 3：真实 FreshRSS category grouping（管理视角，取代 0011 的
 * 「单一未分组」旧假设——BFF /api/v1/subscriptions 早已携带真实分类）：
 * - 分类与 Feed 全部来自 FreshRSS server truth（useSubscriptions /
 *   useCategories），不硬编码任何分类名；无分类 feed → 真实「未分组」；
 * - 本地搜索（客户端过滤当前列表，文案诚实，非全局搜索）；
 * - Feed 行保持 Lumi Mist：icon / title / domain / ⋯（不堆常驻按钮）：
 *   ⋯ → 移动到分类（含新建分类）/ 取消订阅（破坏性双重确认）；
 * - 分类行 ⋯ → 重命名分类；新建分类入口在「移动到分类」对话框内
 *   （FreshRSS 唯一 create-category 通道是移动时自动创建）；
 * - mutation 一律 server-confirmed → invalidate（feeds/categories/
 *   subscriptions/entries），与侧栏同一 truth，无第二套本地缓存；
 * - scope reconciliation：取消订阅后当前 rss-feed scope 失效、重命名
 *   后旧 categoryId 失效 → 自动回退「全部」；
 * - 拖拽手柄不显示（无持久化排序契约）；OPML 导入真实可用（Gate 4：
 *   OpmlImportDialog，严格 preview → confirm → result）。
 *
 * 点 feed 主区域 → selectScope + section 回首页（与侧栏导航同一语义）。 */

import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Download,
  MoreHorizontal,
  Pin,
  PinOff,
  Plus,
  Rss,
  Search,
  ShieldAlert,
  Upload,
} from 'lucide-react'
import {
  useCategories,
  useSetSourceOverrideMutation,
  useSourceAliasesQuery,
  useSourceNotesListQuery,
  useSubscriptions,
} from '../../api/queries'
import type { SourceNotesView } from '../../api/client'
import { listSourceOverrides } from '../../api/client'
import { resolveDisplayTitle } from '../../lib/source-aliases'
import {
  FilterRulesDialog,
  HealthCheckDialog,
  ImportBatchesDialog,
  MigrateSubscriptionDialog,
  MuteListDialog,
  SourcePolicyDialog,
} from '../subscription-w3-panels'
import { useQuery } from '@tanstack/react-query'
import { RsshubRouteParamsDialog } from '../rsshub-route-params-dialog'
import {
  FirstRunChecklist,
  useFirstRunVisible,
} from '../FirstRunChecklist'
import { VolumeOverview } from '../VolumeOverview'
import {
  SourceStaleAlertDialog,
  StaleSourcesPanel,
} from '../SourceStaleAlert'
import { SourceStatsDrawer } from '../SourceStatsDrawer'
import {
  BatchMoveDialog,
  DuplicateSuspectsPanel,
  NotesSearchBox,
  SourceNotesDialog,
} from '../SubscriptionTools'
import type { Subscription } from '../../api/types'
import { useReaderUi, ALL_SCOPE } from '../../store/reader-ui'
import { useOpmlExportFlow } from '../../lib/opml-import'
import AddSourceDialog from '../AddSourceDialog'
import OpmlImportDialog from '../OpmlImportDialog'
import MoveSubscriptionDialog from '../MoveSubscriptionDialog'
import RenameCategoryDialog from '../RenameCategoryDialog'
import SourceAliasDialog from '../SourceAliasDialog'
import UnsubscribeDialog from '../UnsubscribeDialog'
import { Button } from '../ui/Button'
import { IconButton } from '../ui/IconButton'
import { EmptyState } from '../ui/EmptyState'
import { Menu } from '../ui/Menu'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 分类分组节点：真实分类（category.id）或「未分组」。 */
interface SubscriptionGroup {
  key: string // category.id 或 'ungrouped'
  label: string
  subscriptions: Subscription[]
}

/** 真实分组：subscription.category（无 → 未分组，排最后，其余按 label
 * 稳定排序）。禁止硬编码分类名——全部来自 FreshRSS。 */
function groupByCategory(subscriptions: Subscription[]): SubscriptionGroup[] {
  const byKey = new Map<string, SubscriptionGroup>()
  for (const subscription of subscriptions) {
    const category =
      subscription.category &&
      typeof subscription.category.id === 'string' &&
      subscription.category.id
        ? subscription.category
        : null
    if (category !== null) {
      const node = byKey.get(category.id)
      if (node) node.subscriptions.push(subscription)
      else
        byKey.set(category.id, {
          key: category.id,
          label: category.label || category.id,
          subscriptions: [subscription],
        })
    } else {
      const node = byKey.get('ungrouped')
      if (node) node.subscriptions.push(subscription)
      else
        byKey.set('ungrouped', {
          key: 'ungrouped',
          label: '未分组',
          subscriptions: [subscription],
        })
    }
  }
  const groups = [...byKey.values()]
  groups.sort((a, b) => {
    if (a.key === 'ungrouped') return 1
    if (b.key === 'ungrouped') return -1
    return a.label.localeCompare(b.label, 'zh-CN')
  })
  return groups
}

/** feedUrl → 展示域名（解析失败原样返回 URL，不伪造）。 */
function domainOf(feedUrl: string): string {
  try {
    return new URL(feedUrl).hostname
  } catch {
    return feedUrl
  }
}

// ---- F26 订阅置顶/排序（设备本地偏好，localStorage 单 key） ----

/** 置顶存储 key 与上限（超过上限不再新增，诚实禁用而非挤掉最旧）。 */
export const PINNED_FEEDS_STORAGE_KEY = 'lumirss-pinned-feeds'
export const PINNED_FEEDS_LIMIT = 12

/** 读取置顶列表（feedUrl 数组，顺序即展示顺序；corrupted 数据 → []）。 */
export function readPinnedFeeds(storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage): string[] {
  if (storage === null) return []
  try {
    const raw = storage.getItem(PINNED_FEEDS_STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string' && v !== '')
  } catch {
    return []
  }
}

function writePinnedFeeds(list: string[], storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage): void {
  if (storage === null) return
  try {
    storage.setItem(PINNED_FEEDS_STORAGE_KEY, JSON.stringify(list))
  } catch {
    // 写失败静默：置顶是本地增强数据
  }
}

/** 置顶/取消置顶（已满 12 时新增 no-op——按钮侧同步禁用并给 title 提示）。 */
export function togglePinnedFeed(list: string[], feedUrl: string): string[] {
  if (list.includes(feedUrl)) return list.filter((u) => u !== feedUrl)
  if (list.length >= PINNED_FEEDS_LIMIT) return list
  return [...list, feedUrl]
}

/** 置顶区内上移/下移（相邻交换；越界原样返回——按钮侧同步 disabled）。 */
export function movePinnedFeed(list: string[], feedUrl: string, direction: -1 | 1): string[] {
  const index = list.indexOf(feedUrl)
  const target = index + direction
  if (index === -1 || target < 0 || target >= list.length) return list
  const next = [...list]
  const tmp = next[index]!
  next[index] = next[target]!
  next[target] = tmp
  return next
}

export default function SubscriptionsPage() {
  const subscriptions = useSubscriptions()
  const categories = useCategories(true)

  const selectScope = useReaderUi((s) => s.selectScope)
  const selectView = useReaderUi((s) => s.selectView)
  const selectSection = useReaderUi((s) => s.selectSection)
  const scope = useReaderUi((s) => s.scope)

  // 本地过滤（仅当前已加载的订阅——客户端过滤，非全局搜索）
  const [query, setQuery] = useState('')
  // 收起集合（管理视角默认全展开；只记收起的组）
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  // 0013 Gate 2：添加订阅入口；Gate 4：OPML 导入入口
  const [addOpen, setAddOpen] = useState(false)
  const [opmlOpen, setOpmlOpen] = useState(false)
  // 0014a Gate 1：订阅管理页导出 OPML（与设置共享 useOpmlExportFlow）
  const opmlExport = useOpmlExportFlow()
  // 0013 Gate 3：管理对话框目标（null = 关闭）
  const [moveTarget, setMoveTarget] = useState<Subscription | null>(null)
  const [unsubscribeTarget, setUnsubscribeTarget] = useState<Subscription | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ id: string; label: string } | null>(null)
  // N013：来源改名（服务端别名 + 历史）对话框目标
  const [aliasTarget, setAliasTarget] = useState<Subscription | null>(null)
  // F26：置顶订阅（localStorage 持久；顺序即置顶区展示顺序）
  const [pinned, setPinned] = useState<string[]>(() => readPinnedFeeds())
  // F001：异常来源筛选开关 + 新鲜度预警设置目标
  const [stalePanelOpen, setStalePanelOpen] = useState(false)
  const [staleTarget, setStaleTarget] = useState<{
    feedUrl: string
    title: string
  } | null>(null)
  // F023/F024/F025/F026/F035/F037/F038：来源统计与工具抽屉目标
  const [statsTarget, setStatsTarget] = useState<{
    feedUrl: string
    title: string
  } | null>(null)
  // F004：查重面板开关
  const [duplicatePanelOpen, setDuplicatePanelOpen] = useState(false)
  // F003/F006：多选模式（选中集合为 subscriptionRef）
  const [multiSelect, setMultiSelect] = useState(false)
  const [checkedRefs, setCheckedRefs] = useState<Set<string>>(new Set())
  // F006：批量移动对话框
  const [batchMoveOpen, setBatchMoveOpen] = useState(false)
  // F005：备注对话框目标 + 备注关键词过滤（前端过滤当前列表）
  const [notesTarget, setNotesTarget] = useState<{
    subscriptionRef: string
    title: string
  } | null>(null)
  const [notesFilter, setNotesFilter] = useState<string | null>(null)
  // W3：F044 迁移 / F045 内容过滤 / F048+F055 来源设置 / F046 静音列表 /
  // F049 导入记录 / F050 维护检查 的对话框目标与开关。
  const [migrateTarget, setMigrateTarget] = useState<Subscription | null>(null)
  const [filterTarget, setFilterTarget] = useState<Subscription | null>(null)
  const [policyTarget, setPolicyTarget] = useState<Subscription | null>(null)
  const [routeParamsTarget, setRouteParamsTarget] = useState<Subscription | null>(null)
  const [muteListOpen, setMuteListOpen] = useState(false)
  const [importBatchesOpen, setImportBatchesOpen] = useState(false)
  const [healthCheckOpen, setHealthCheckOpen] = useState(false)

  const toggleChecked = (ref: string) => {
    setCheckedRefs((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

  const togglePin = (feedUrl: string) => {
    setPinned((prev) => {
      const next = togglePinnedFeed(prev, feedUrl)
      writePinnedFeeds(next)
      return next
    })
  }
  const movePin = (feedUrl: string, direction: -1 | 1) => {
    setPinned((prev) => {
      const next = movePinnedFeed(prev, feedUrl, direction)
      writePinnedFeeds(next)
      return next
    })
  }

  // F005：后端 note_search（返回命中的备注），仅用于前端当前列表过滤
  const notesList = useSourceNotesListQuery(notesFilter)
  const sourceNotesIndex = useMemo(() => {
    const map = new Map<string, SourceNotesView>()
    for (const item of notesList.data?.items ?? []) map.set(item.subscriptionRef, item)
    return map
  }, [notesList.data])

  // N013：服务端别名（feedUrl → 显示名；时间线/订阅展示「服务端赢」）
  const aliasesQuery = useSourceAliasesQuery()
  const serverAliases = useMemo(
    () =>
      aliasesQuery.data?.items
        ? new Map(aliasesQuery.data.items.map((alias) => [alias.feedUrl, alias.customName]))
        : undefined,
    [aliasesQuery.data],
  )

  const filtered = useMemo(() => {
    const all = subscriptions.data ?? []
    const q = query.trim().toLowerCase()
    let list = all
    if (q) {
      list = list.filter(
        (s) =>
          s.title.toLowerCase().includes(q) ||
          s.feedUrl.toLowerCase().includes(q) ||
          (s.category?.label.toLowerCase().includes(q) ?? false),
      )
    }
    if (notesFilter !== null) {
      // F005：备注关键词过滤（客户端过滤当前列表，文案诚实）
      list = list.filter((s) => {
        const note = sourceNotesIndex.get(s.subscriptionRef)
        if (note === undefined) return false
        return (
          (note.note ?? '').includes(notesFilter) ||
          (note.reason ?? '').includes(notesFilter) ||
          (note.maintenanceLog ?? '').includes(notesFilter)
        )
      })
    }
    return list
  }, [subscriptions.data, query, notesFilter, sourceNotesIndex])

  const groups = useMemo(() => groupByCategory(filtered), [filtered])

  // F26：置顶区数据（按 pinned 顺序取订阅；已取消订阅的残留 url 静默略过）
  const pinnedSubs = useMemo(() => {
    const all = filtered
    return pinned
      .map((feedUrl) => all.find((s) => s.feedUrl === feedUrl))
      .filter((s): s is Subscription => s !== undefined)
  }, [filtered, pinned])

  // scope reconciliation（Gate 3）：mutation → invalidate → server truth
  // 更新后，清掉指向已删除 feed / 已重命名旧 categoryId 的 stale scope，
  // 回退「全部」。数据未加载完成时跳过（避免误清）。
  useEffect(() => {
    const subs = subscriptions.data
    if (subs === undefined) return
    if (scope.kind === 'rss-feed') {
      if (!subs.some((s) => s.feedUrl === scope.feedUrl)) {
        selectScope(ALL_SCOPE)
      }
    } else if (scope.kind === 'rss-category') {
      const cats = categories.data
      if (cats !== undefined && !cats.some((c) => c.id === scope.categoryId)) {
        selectScope(ALL_SCOPE)
      }
    }
  }, [subscriptions.data, categories.data, scope, selectScope])

  const overrideMutation = useSetSourceOverrideMutation()
  // F046：静音列表数据（服务端 overrides；过期过滤在 MuteListDialog 内做）
  const overridesQuery = useQuery({
    queryKey: ['source-overrides'],
    queryFn: () => listSourceOverrides(),
    enabled: muteListOpen,
  })
  // F40：首启向导（尚无任何订阅且未被关闭时显示）
  const firstRunVisible = useFirstRunVisible()
  const [firstRunDismissed, setFirstRunDismissed] = useState(false)

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (subscriptions.isPending) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" aria-label="订阅加载中">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    )
  }

  if (subscriptions.isError) {
    return (
      <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
        <p>订阅加载失败</p>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          {subscriptions.error.message}
        </p>
        <Button size="sm" onClick={() => subscriptions.refetch()} className="mt-2">
          重试
        </Button>
      </div>
    )
  }

  const total = subscriptions.data?.length ?? 0

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AddSourceDialog open={addOpen} onClose={() => setAddOpen(false)} />
      <OpmlImportDialog open={opmlOpen} onClose={() => setOpmlOpen(false)} />
      <MoveSubscriptionDialog
        open={moveTarget !== null}
        onClose={() => setMoveTarget(null)}
        subscription={moveTarget}
      />
      <UnsubscribeDialog
        open={unsubscribeTarget !== null}
        onClose={() => setUnsubscribeTarget(null)}
        subscription={unsubscribeTarget}
      />
      <RenameCategoryDialog
        open={renameTarget !== null}
        onClose={() => setRenameTarget(null)}
        category={renameTarget}
      />
      {aliasTarget !== null && (
        <SourceAliasDialog
          open
          onClose={() => setAliasTarget(null)}
          feedUrl={aliasTarget.feedUrl}
          title={aliasTarget.title}
        />
      )}
      <SourceStaleAlertDialog
        open={staleTarget !== null}
        onClose={() => setStaleTarget(null)}
        subscription={staleTarget}
      />
      <SourceStatsDrawer
        open={statsTarget !== null}
        onClose={() => setStatsTarget(null)}
        feedUrl={statsTarget?.feedUrl ?? ''}
        title={statsTarget?.title ?? ''}
      />
      <SourceNotesDialog
        open={notesTarget !== null}
        onClose={() => setNotesTarget(null)}
        subscription={notesTarget}
      />
      <BatchMoveDialog
        open={batchMoveOpen}
        onClose={() => setBatchMoveOpen(false)}
        refs={[...checkedRefs]}
        titleOf={(ref) =>
          (subscriptions.data ?? []).find((s) => s.subscriptionRef === ref)?.title ?? ref
        }
      />
      {migrateTarget !== null && (
        <MigrateSubscriptionDialog
          open
          onClose={() => setMigrateTarget(null)}
          subscriptionRef={migrateTarget.subscriptionRef}
          feedUrl={migrateTarget.feedUrl}
          title={migrateTarget.title}
        />
      )}
      {filterTarget !== null && (
        <FilterRulesDialog
          open
          onClose={() => setFilterTarget(null)}
          feedUrl={filterTarget.feedUrl}
          title={filterTarget.title}
        />
      )}
      {policyTarget !== null && (
        <SourcePolicyDialog
          open
          onClose={() => setPolicyTarget(null)}
          feedUrl={policyTarget.feedUrl}
          title={policyTarget.title}
        />
      )}
      {routeParamsTarget !== null && (
        <RsshubRouteParamsDialog open onClose={() => setRouteParamsTarget(null)} subscription={routeParamsTarget} />
      )}
      <MuteListDialog
        open={muteListOpen}
        onClose={() => setMuteListOpen(false)}
        overrides={(overridesQuery.data?.items ?? []).map((item) => ({
          feedUrl: item.feedUrl,
          hiddenUntil: item.hiddenUntil,
          staleAlertHours: item.staleAlertHours,
        }))}
        onUnmute={(feedUrl) => overrideMutation.mutate({ feedUrl, hiddenUntil: null })}
      />
      <ImportBatchesDialog open={importBatchesOpen} onClose={() => setImportBatchesOpen(false)} />
      <HealthCheckDialog
        open={healthCheckOpen}
        onClose={() => setHealthCheckOpen(false)}
        subscriptions={(subscriptions.data ?? []).map((sub) => ({
          subscriptionRef: sub.subscriptionRef,
          title: sub.title,
          feedUrl: sub.feedUrl,
        }))}
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* F40：首启向导（尚无订阅且未被关闭时显示；可整体关闭） */}
        {firstRunVisible && !firstRunDismissed ? (
          <FirstRunChecklist onClose={() => setFirstRunDismissed(true)} />
        ) : null}
        {/* F12：收件量概览（可折叠；识别信息过载与异常停更） */}
        <VolumeOverview />
        {/* 搜索订阅源（本地过滤，文案诚实） */}
        <div className="relative mb-3">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索订阅源（当前列表）"
            aria-label="搜索订阅源"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </div>

        {/* 顶部动作：添加来源（0014：RSS/Atom + 网站发现 + RSSHub）/ OPML 导入 / OPML 导出 */}
        <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="订阅管理动作">
          <Button
            variant="secondary"
            onClick={() => setAddOpen(true)}
            aria-haspopup="dialog"
            className="text-xs"
          >
            <Plus aria-hidden className="size-3.5" />
            添加来源
          </Button>
          <Button
            variant="secondary"
            onClick={() => setOpmlOpen(true)}
            aria-haspopup="dialog"
            className="text-xs"
          >
            <Upload aria-hidden className="size-3.5" />
            导入 OPML
          </Button>
          <Button
            variant="secondary"
            onClick={() => opmlExport.exportOnce()}
            disabled={opmlExport.busy}
            className="text-xs"
          >
            <Download aria-hidden className="size-3.5" />
            {opmlExport.busy ? '导出中…' : '导出 OPML'}
          </Button>
          {/* W3 工具：静音列表（F046）/ 导入记录（F049）/ 维护检查（F050） */}
          <Button variant="secondary" className="text-xs" onClick={() => setMuteListOpen(true)} aria-haspopup="dialog">
            静音列表
          </Button>
          <Button variant="secondary" className="text-xs" onClick={() => setImportBatchesOpen(true)} aria-haspopup="dialog">
            导入记录
          </Button>
          <Button variant="secondary" className="text-xs" onClick={() => setHealthCheckOpen(true)} aria-haspopup="dialog">
            维护检查
          </Button>
          {/* F001：异常来源筛选开关（aria-pressed = 筛选态可见性） */}
          <Button
            variant={stalePanelOpen ? 'primary' : 'secondary'}
            onClick={() => setStalePanelOpen((v) => !v)}
            aria-pressed={stalePanelOpen}
            className="text-xs"
          >
            <ShieldAlert aria-hidden className="size-3.5" />
            异常来源
          </Button>
          {/* F004：查重面板开关 */}
          <Button
            variant={duplicatePanelOpen ? 'primary' : 'secondary'}
            onClick={() => setDuplicatePanelOpen((v) => !v)}
            aria-pressed={duplicatePanelOpen}
            className="text-xs"
          >
            查重
          </Button>
          {/* F003/F006：多选模式开关 */}
          <Button
            variant={multiSelect ? 'primary' : 'secondary'}
            onClick={() => {
              setMultiSelect((v) => !v)
              setCheckedRefs(new Set())
            }}
            aria-pressed={multiSelect}
            className="text-xs"
          >
            多选
          </Button>
        </div>
        {/* F001：超期来源面板（开关展开；含 basis 标注与空态） */}
        {stalePanelOpen && <StaleSourcesPanel />}
        {/* F004：重复候选面板（只读） */}
        {duplicatePanelOpen && <DuplicateSuspectsPanel />}
        {/* F003/F006：多选操作栏（导出所选 OPML / 移动到分类） */}
        {multiSelect && (
          <div
            className="mb-3 flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2"
            role="group"
            aria-label="多选操作"
          >
            <span className="text-xs text-[var(--lumi-text-secondary)]">
              已选 {checkedRefs.size}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={checkedRefs.size === 0 || opmlExport.busy}
              onClick={() =>
                opmlExport.exportOnce({ subscriptionRefs: [...checkedRefs] })
              }
              className="text-xs"
            >
              <Download aria-hidden className="size-3.5" />
              {opmlExport.busy ? '导出中…' : '导出所选 OPML'}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={checkedRefs.size === 0}
              onClick={() => setBatchMoveOpen(true)}
              className="text-xs"
            >
              移动到分类…
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setCheckedRefs(new Set())}
              disabled={checkedRefs.size === 0}
              className="text-xs"
            >
              清空
            </Button>
          </div>
        )}
        {/* F005：备注关键词过滤框（过滤当前列表） */}
        <div className="mb-3">
          <NotesSearchBox onSearch={setNotesFilter} />
        </div>
        {opmlExport.error !== null && (
          <p role="alert" className="mb-3 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
            {opmlExport.error}
          </p>
        )}
        {opmlExport.done && (
          <p role="status" className="mb-3 text-xs text-[var(--lumi-text-secondary)]">
            已开始下载 OPML 文件
          </p>
        )}

        {/* F26：置顶区（localStorage 持久；上移/下移 + 取消置顶；点主区域
            进入该订阅范围，与分类区内行为一致；不修改上游订阅） */}
        {pinnedSubs.length > 0 && (
          <section
            aria-label="置顶订阅"
            data-testid="pinned-section"
            className="mb-2 overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]"
          >
            <h3 className="px-3.5 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
              置顶
            </h3>
            <ul className="divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
              {pinnedSubs.map((subscription, index) => (
                <li key={subscription.feedUrl} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => {
                      selectSection('home')
                      selectView('all')
                      selectScope({ kind: 'rss-feed', feedUrl: subscription.feedUrl })
                    }}
                    className={cx(
                      'flex min-h-14 min-w-0 flex-1 items-center gap-3 px-3.5 py-2.5 text-left',
                      'transition-colors duration-[var(--lumi-motion-fast)]',
                      'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
                      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    )}
                  >
                    <span
                      aria-hidden
                      className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]"
                    >
                      <Pin className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]"
                        title={subscription.title}
                      >
                        {resolveDisplayTitle(subscription.feedUrl, subscription.title, serverAliases)}
                      </span>
                      <span
                        className="block truncate text-xs text-[var(--lumi-text-tertiary)]"
                        title={subscription.feedUrl}
                      >
                        {domainOf(subscription.feedUrl)}
                      </span>
                    </span>
                  </button>
                  <IconButton
                    icon={<ArrowUp aria-hidden className="size-4" />}
                    label={`上移「${subscription.title}」`}
                    size="sm"
                    touch
                    disabled={index === 0}
                    onClick={() => movePin(subscription.feedUrl, -1)}
                  />
                  <IconButton
                    icon={<ArrowDown aria-hidden className="size-4" />}
                    label={`下移「${subscription.title}」`}
                    size="sm"
                    touch
                    disabled={index === pinnedSubs.length - 1}
                    onClick={() => movePin(subscription.feedUrl, 1)}
                  />
                  <IconButton
                    icon={<PinOff aria-hidden className="size-4" />}
                    label={`取消置顶「${subscription.title}」`}
                    size="sm"
                    touch
                    onClick={() => togglePin(subscription.feedUrl)}
                  />
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 真实分类分组（全部来自 FreshRSS；无硬编码分类名） */}
        {total === 0 ? (
          <EmptyState
            icon={<Rss aria-hidden className="size-8" />}
            title="还没有订阅源"
            description="点击「添加 RSS」订阅第一个源。"
          />
        ) : (
          <div className="flex flex-col gap-2">
            {groups.length === 0 && (
              <EmptyState
                icon={<Search aria-hidden className="size-8" />}
                title="没有匹配的订阅源"
                description="换个关键词试试。"
              />
            )}
            {groups.map((group) => {
              const expanded = !collapsedGroups.has(group.key)
              const isUngrouped = group.key === 'ungrouped'
              return (
                <div
                  key={group.key}
                  className="overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]"
                >
                  {/* 分类行：disclosure（主区域）+ ⋯ 分类操作（真实分类） */}
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.key)}
                      aria-expanded={expanded}
                      aria-controls={`subscriptions-group-${encodeURIComponent(group.key)}`}
                      aria-label={`${group.label}，${group.subscriptions.length} 个订阅源`}
                      className="flex min-h-11 flex-1 items-center gap-2 px-3.5 py-2 text-left"
                    >
                      <ChevronDown
                        aria-hidden
                        className={cx(
                          'size-4 text-[var(--lumi-text-tertiary)] transition-transform duration-[var(--lumi-motion-fast)]',
                          !expanded && '-rotate-90',
                        )}
                      />
                      <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
                        {group.label}
                      </span>
                      <span className="text-xs text-[var(--lumi-text-tertiary)]">
                        {group.subscriptions.length}
                      </span>
                    </button>
                    {!isUngrouped && (
                      <Menu
                        trigger={({ triggerProps }) => (
                          <button
                            {...triggerProps}
                            aria-label={`「${group.label}」分类操作`}
                            className={cx(
                              'mr-2 flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
                              'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
                              'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                            )}
                          >
                            <MoreHorizontal aria-hidden className="size-4" />
                          </button>
                        )}
                        items={[
                          { key: 'rename', content: '重命名分类' },
                        ]}
                        onSelect={() =>
                          setRenameTarget({ id: group.key, label: group.label })
                        }
                      />
                    )}
                  </div>

                  {expanded && (
                    <ul
                      id={`subscriptions-group-${encodeURIComponent(group.key)}`}
                      className="divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]"
                    >
                      {group.subscriptions.map((subscription) => (
                        <li key={subscription.subscriptionRef} className="flex items-center">
                          {/* F003/F006：多选勾选框（44px 触控目标由行高与
                              min-h-11 保证；aria-label 独立命名） */}
                          {multiSelect && (
                            <span className="flex min-h-11 items-center pl-2">
                              <input
                                type="checkbox"
                                aria-label={`选择「${subscription.title}」`}
                                checked={checkedRefs.has(subscription.subscriptionRef)}
                                onChange={() => toggleChecked(subscription.subscriptionRef)}
                                className="size-5 accent-[var(--lumi-accent)]"
                              />
                            </span>
                          )}
                          {/* 主区域：icon / title / domain（Lumi Mist 行） */}
                          <button
                            type="button"
                            onClick={() => {
                              // 与侧栏 feed 导航同一语义：切回首页 + scope
                              selectSection('home')
                              selectView('all')
                              selectScope({ kind: 'rss-feed', feedUrl: subscription.feedUrl })
                            }}
                            className={cx(
                              'flex min-h-14 min-w-0 flex-1 items-center gap-3 px-3.5 py-2.5 text-left',
                              'transition-colors duration-[var(--lumi-motion-fast)]',
                              'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
                              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                            )}
                          >
                            {/* 统一 RSS 图标（无 favicon 契约，不抓取外部图片） */}
                            <span
                              aria-hidden
                              className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]"
                            >
                              <Rss className="size-4" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span
                                className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]"
                                title={subscription.title}
                              >
                                {resolveDisplayTitle(subscription.feedUrl, subscription.title, serverAliases)}
                              </span>
                              <span
                                className="block truncate text-xs text-[var(--lumi-text-tertiary)]"
                                title={subscription.feedUrl}
                              >
                                {domainOf(subscription.feedUrl)}
                              </span>
                            </span>
                          </button>
                          {/* F26 置顶切换（aria-pressed；已满 12 且未置顶时
                              禁用——不静默挤掉最旧的置顶） */}
                          <IconButton
                            icon={<Pin aria-hidden className="size-4" />}
                            label={
                              pinned.includes(subscription.feedUrl)
                                ? `取消置顶「${subscription.title}」`
                                : `置顶「${subscription.title}」`
                            }
                            aria-pressed={pinned.includes(subscription.feedUrl)}
                            size="sm"
                            touch
                            disabled={!pinned.includes(subscription.feedUrl) && pinned.length >= PINNED_FEEDS_LIMIT}
                            style={{
                              color: pinned.includes(subscription.feedUrl)
                                ? 'var(--lumi-accent)'
                                : 'var(--lumi-text-tertiary)',
                            }}
                            onClick={() => togglePin(subscription.feedUrl)}
                          />
                          {/* ⋯ Feed 操作菜单（不堆常驻按钮） */}
                          <Menu
                            trigger={({ triggerProps }) => (
                              <button
                                {...triggerProps}
                                aria-label={`「${subscription.title}」的操作`}
                                className={cx(
                                  'mr-2 flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
                                  'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
                                  'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                                )}
                              >
                                <MoreHorizontal aria-hidden className="size-4" />
                              </button>
                            )}
                            items={[
                              { key: 'move', content: '移动到分类' },
                              { key: 'stats', content: '统计与工具' },
                              { key: 'alias', content: '来源改名（别名）' },
                              { key: 'staleAlert', content: '新鲜度预警' },
                              { key: 'notes', content: '备注/维护记录' },
                              { key: 'migrate', content: '更换订阅地址' },
                              { key: 'filterRules', content: '内容过滤' },
                              { key: 'sourcePolicy', content: '来源设置（正文策略/阅读外观）' },
                              { key: 'routeParams', content: '路由参数' },
                              { key: 'hide7', content: '隐藏 7 天（F11）' },
                              { key: 'hide30', content: '隐藏 30 天' },
                              { key: 'unhide', content: '取消隐藏' },
                              { key: 'readFromNow', content: '阅读起点=现在（F13）' },
                              { key: 'clearStart', content: '清除阅读起点' },
                              { key: 'unsubscribe', content: '取消订阅' },
                            ]}
                            onSelect={(key) => {
                              if (key === 'move') setMoveTarget(subscription)
                              else if (key === 'stats')
                                setStatsTarget({
                                  feedUrl: subscription.feedUrl,
                                  title: subscription.title,
                                })
                              else if (key === 'alias') setAliasTarget(subscription)
                              else if (key === 'staleAlert')
                                setStaleTarget({
                                  feedUrl: subscription.feedUrl,
                                  title: subscription.title,
                                })
                              else if (key === 'notes')
                                setNotesTarget({
                                  subscriptionRef: subscription.subscriptionRef,
                                  title: subscription.title,
                                })
                              else if (key === 'unsubscribe') setUnsubscribeTarget(subscription)
                              else if (key === 'hide7')
                                overrideMutation.mutate({
                                  feedUrl: subscription.feedUrl,
                                  hiddenUntil: new Date(Date.now() + 7 * 86_400_000).toISOString(),
                                })
                              else if (key === 'hide30')
                                overrideMutation.mutate({
                                  feedUrl: subscription.feedUrl,
                                  hiddenUntil: new Date(Date.now() + 30 * 86_400_000).toISOString(),
                                })
                              else if (key === 'unhide')
                                overrideMutation.mutate({ feedUrl: subscription.feedUrl, hiddenUntil: null })
                              else if (key === 'readFromNow')
                                overrideMutation.mutate({
                                  feedUrl: subscription.feedUrl,
                                  showFrom: new Date().toISOString(),
                                })
                              else if (key === 'clearStart')
                                overrideMutation.mutate({ feedUrl: subscription.feedUrl, showFrom: null })
                              // N020：关注级别在来源设置对话框中设置（行菜单入口）。
                              else if (key === 'sourcePolicy') setPolicyTarget(subscription)
                              // N024：F047 路由参数对话框（行菜单入口；差异对照在其内）。
                              else if (key === 'routeParams') setRouteParamsTarget(subscription)
                            }}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
