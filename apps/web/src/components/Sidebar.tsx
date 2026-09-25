import {
  Archive,
  Bookmark,
  Bot,
  ChevronDown,
  Clock,
  FileText,
  FolderOpen,
  Globe,
  Inbox,
  Layers,
  Link2,
  Mail,
  Plus,
  Rss,
  Search as SearchIcon,
  Star,
  Tags,
  Zap,
} from 'lucide-react'
import { Suspense, lazy, useMemo, useState, memo } from 'react'
import { useFeeds, usePinnedViewCount, usePinnedViews } from '../api/queries'
import type { Feed } from '../api/types'
import { useReaderUi, ALL_SCOPE } from '../store/reader-ui'
import type { ContentScope } from '../lib/navigation'
import { requestOpenSettings } from './settings/settings-bridge'
import { Skeleton } from './ui/Skeleton'
const AddSourceDialog = lazy(() => import('./AddSourceDialog'))
import SidebarHeader from './SidebarHeader'
import { cx } from './ui/cx'
import RecentReadsInline from './RecentReadsInline'
const RecentWorkspacesCard = lazy(() => import('./RecentWorkspacesCard'))
import ContinueReadingCard from './ContinueReadingCard'
import AccountMenu from './AccountMenu'

/** Sidebar — 信息架构分组导航（0011 阻断修复：真实分类树 + 四级 Scope）。
 *
 * 结构：
 *   信息来源：全部信息源（scope=all）/ RSS 订阅（scope=rss，tree 含
 *            FreshRSS 真实分类 + 未分组）+ Phase 2 项（禁用+徽标）
 *   工作区：  稍后读（view=read-later）/ 收藏（view=starred）
 *
 * 0011 阻断修复关键语义（§6–§9）：
 * - RSS 行主区域（icon+label）→ scope=全部 RSS；chevron → 只展开/收起
 *   tree（stopPropagation，不改 scope）；两者行为完全分离；
 * - 分类同理：主区域 → scope=该分类（服务端 label stream），chevron →
 *   只展开该分类下的 feeds；
 * - 分类来自 FreshRSS 真实数据（feed.category），按 category.id 合并
 *   （§3），无分类 feed 归入「未分组」（§4），不硬编码；
 * - Layout 展开状态（rssTree/expandedCategories）为组件本地 state，
 *   与导航 scope 正交（§17）。 */

/** 可用导航项（真实导航行为） */
function NavItem({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'true' : undefined}
      className={cx(
        'flex w-full items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
        'min-h-8 py-1 max-lg:min-h-11 max-lg:items-center',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        active
          ? 'bg-[var(--lumi-surface-selected)] font-medium text-[var(--lumi-accent-text)]'
          : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
      )}
    >
      {children}
    </button>
  )
}


/** 分组标题 */
function GroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pb-0.5 pt-3 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
      {children}
    </p>
  )
}

/** 分类柔彩确定性分配：同 feed 永远同色（按 feedUrl 哈希），不存状态。 */
const CATEGORY_COLORS = [
  'var(--lumi-category-blue)',
  'var(--lumi-category-green)',
  'var(--lumi-category-orange)',
  'var(--lumi-category-purple)',
  'var(--lumi-category-cyan)',
  'var(--lumi-category-rose)',
] as const

function feedColor(feedUrl: string): string {
  let hash = 0
  for (let i = 0; i < feedUrl.length; i++) {
    hash = (hash * 31 + feedUrl.charCodeAt(i)) | 0
  }
  return CATEGORY_COLORS[Math.abs(hash) % CATEGORY_COLORS.length]
}

const icon16 = 'size-4 shrink-0'

/** 分类树节点：真实分类（按 category.id 合并）或「未分组」。 */
interface CategoryNode {
  key: string // category.id 或 'ungrouped'
  label: string
  feeds: Feed[]
}

/** §3/§45 合并：feed.category.id → unique node → feeds[]（不按 name 拼接）。
 * 防御：category 形状异常（undefined/缺字段）时归入未分组，不崩溃。 */
export function mergeFeedsByCategory(feeds: Feed[]): CategoryNode[] {
  const byKey = new Map<string, CategoryNode>()
  for (const feed of feeds) {
    const category =
      feed.category && typeof feed.category.id === 'string' && feed.category.id
        ? feed.category
        : null
    if (category !== null) {
      const node = byKey.get(category.id)
      if (node) node.feeds.push(feed)
      else
        byKey.set(category.id, {
          key: category.id,
          label: category.label || category.id,
          feeds: [feed],
        })
    } else {
      // §4：无分类 feed 统一进入「未分组」
      const node = byKey.get('ungrouped')
      if (node) node.feeds.push(feed)
      else byKey.set('ungrouped', { key: 'ungrouped', label: '未分组', feeds: [feed] })
    }
  }
  const nodes = [...byKey.values()]
  // 未分组排最后，其余按 label 稳定排序
  nodes.sort((a, b) => {
    if (a.key === 'ungrouped') return 1
    if (b.key === 'ungrouped') return -1
    return a.label.localeCompare(b.label, 'zh-CN')
  })
  return nodes
}

/** RSS 订阅树（0011：主区域=scope / chevron=tree，两行为完全分离）。
 *
 * Layout 状态（tree 展开、分类展开）为本地 state——tree 收起时仍可
 * 处于 RSS scope（§17 合法）。
 *
 * 0014a Gate 1：桌面上下文（onAddSource 传入）在 RSS 行尾部渲染
 * 「+ 添加来源」入口（复用 AddSourceDialog，订阅逻辑零复制）。 */
function RssTree({
  onNavigate,
  onAddSource,
}: {
  onNavigate?: () => void
  onAddSource?: () => void
}) {
  const scope = useReaderUi((s) => s.scope)
  const view = useReaderUi((s) => s.view)
  const selectSection = useReaderUi((s) => s.selectSection)
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectView = useReaderUi((s) => s.selectView)
  const feeds = useFeeds()

  // Layout（本地）：tree 展开 + 各分类展开（新会话默认全收起）
  const [treeExpanded, setTreeExpanded] = useState(false)
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())

  const categories = useMemo(
    () => (feeds.data ? mergeFeedsByCategory(feeds.data) : []),
    [feeds.data],
  )

  const rssScopeActive = scope.kind === 'rss' && view === 'all'

  const goScope = (next: ContentScope) => {
    selectSection('home')
    selectScope(next)
    selectView('all')
    onNavigate?.()
  }

  const toggleCategory = (key: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div>
      {/* F035：固定视图块（pin_order 顺序 + 服务端真实计数徽标；查询失败显示 '—'） */}
      <PinnedViewsBlock />

      {/* RSS 行：主区域（→ 全部 RSS）+ chevron（→ tree 展开/收起） */}
      <div
        className={cx(
          'flex items-center gap-1 rounded-[var(--lumi-radius-md)]',
          rssScopeActive
            ? 'bg-[var(--lumi-surface-selected)]'
            : 'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
        )}
      >
        <button
          type="button"
          onClick={() => goScope({ kind: 'rss' })}
          aria-current={rssScopeActive ? 'true' : undefined}
          className={cx(
            'flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
            'min-h-8 py-1 max-lg:min-h-11 max-lg:items-center',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            rssScopeActive
              ? 'font-medium text-[var(--lumi-accent-text)]'
              : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
          )}
        >
          <Rss aria-hidden className={icon16} />
          <span className="truncate">RSS 订阅</span>
        </button>
        <button
          type="button"
          onClick={() => setTreeExpanded((v) => !v)}
          aria-expanded={treeExpanded}
          aria-controls="sidebar-rss-tree"
          aria-label={treeExpanded ? '收起 RSS 分类' : '展开 RSS 分类'}
          className={cx(
            'mr-1 flex size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
            'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <ChevronDown
            aria-hidden
            className={cx('size-4 transition-transform duration-[var(--lumi-motion-fast)]', treeExpanded && 'rotate-180')}
          />
        </button>
        {/* 0014a Gate 1：桌面添加来源（RSS 订阅 → +；aria-label/title 承载
            语义。移动端入口在订阅页「添加来源」按钮——本按钮仅桌面上下文
            渲染，与订阅管理页共用同一个 AddSourceDialog，零复制逻辑。） */}
        {onAddSource !== undefined && (
          <button
            type="button"
            onClick={onAddSource}
            aria-label="添加来源"
            title="添加来源"
            className={cx(
              'mr-1 flex size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
              'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
              'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            )}
          >
            <Plus aria-hidden className="size-4" />
          </button>
        )}
      </div>

      {treeExpanded && (
        <div id="sidebar-rss-tree" className="flex flex-col gap-0.5 pl-2.5">
          {feeds.isPending && (
            <div className="flex flex-col gap-1.5 px-2.5 pt-1" aria-label="订阅加载中">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          )}

          {feeds.isError && (
            <div className="px-2.5 py-2 text-sm text-[var(--lumi-danger)]">
              <p>订阅加载失败</p>
              <button
                type="button"
                onClick={() => feeds.refetch()}
                className="mt-1 min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-xs transition-colors hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                重试
              </button>
            </div>
          )}

          {feeds.data?.length === 0 && (
            <p className="px-2.5 py-2 text-xs text-[var(--lumi-text-tertiary)]">暂无订阅</p>
          )}

          {categories.map((category) => {
            const isUngrouped = category.key === 'ungrouped'
            // 未分组：无服务端分类契约（FreshRSS 实际上总归默认分类，此节点
            // 仅在契约异常时出现）→ 主区域不可作为 scope，仅 chevron 展开。
            const categoryScope: ContentScope = {
              kind: 'rss-category',
              categoryId: category.key,
              categoryLabel: category.label,
            }
            const categoryActive =
              !isUngrouped &&
              scope.kind === 'rss-category' &&
              scope.categoryId === category.key
            const catExpanded = expandedCategories.has(category.key)
            return (
              <div key={category.key}>
                {/* 分类行：主区域（→ 该分类 scope）+ chevron（→ 展开 feeds） */}
                <div
                  className={cx(
                    'flex items-center gap-1 rounded-[var(--lumi-radius-md)]',
                    categoryActive
                      ? 'bg-[var(--lumi-surface-selected)]'
                      : 'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (!isUngrouped) goScope(categoryScope)
                    }}
                    disabled={isUngrouped}
                    title={isUngrouped ? '未分组的订阅源' : undefined}
                    aria-current={categoryActive ? 'true' : undefined}
                    className={cx(
                      'flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1 text-left text-sm',
                      'min-h-8 max-lg:min-h-11 max-lg:items-center',
                      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                      categoryActive
                        ? 'font-medium text-[var(--lumi-accent-text)]'
                        : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cx('size-2 shrink-0 rounded-sm', category.key === 'ungrouped' ? 'border border-[var(--lumi-border)] bg-transparent' : 'rounded-[3px]')}
                      style={
                        category.key === 'ungrouped'
                          ? undefined
                          : { backgroundColor: feedColor(category.key) }
                      }
                    />
                    <span className="truncate" title={category.label}>
                      {category.label}
                    </span>
                    <span
                      className={cx(
                        'shrink-0 text-[11px]',
                        // 分类选中时落在选中表面上，tertiary 不满足 WCAG AA
                        categoryActive
                          ? 'text-[var(--lumi-text-secondary)]'
                          : 'text-[var(--lumi-text-tertiary)]',
                      )}
                    >
                      {category.feeds.length}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleCategory(category.key)}
                    aria-expanded={catExpanded}
                    aria-label={catExpanded ? `收起 ${category.label} 的订阅源` : `展开 ${category.label} 的订阅源`}
                    className={cx(
                      'mr-1 flex size-7 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)]',
                      'text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)]',
                      'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    )}
                  >
                    <ChevronDown
                      aria-hidden
                      className={cx('size-4 transition-transform duration-[var(--lumi-motion-fast)]', catExpanded && 'rotate-180')}
                    />
                  </button>
                </div>

                {catExpanded &&
                  category.feeds.map((feed) => (
                    <NavItem
                      key={feed.feedUrl}
                      active={scope.kind === 'rss-feed' && scope.feedUrl === feed.feedUrl}
                      onClick={() => goScope({ kind: 'rss-feed', feedUrl: feed.feedUrl })}
                    >
                      <span
                        aria-hidden="true"
                        className="size-1.5 shrink-0 rounded-full"
                        style={{ backgroundColor: feedColor(feed.feedUrl) }}
                      />
                      <span className="truncate" title={feed.title}>
                        <span data-privacy-text="">{feed.title}</span>
                      </span>
                    </NavItem>
                  ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** memo 边界：props 仅 onNavigate（App 不传 / 抽屉传稳定的 zustand
 * action）。selectedEntryRef 变化时 App 重渲染，但 Sidebar 自身不订阅
 * selection——memo 避免整个订阅源树随每次文章选择重渲染。 */
function Sidebar({
  onNavigate,
}: {
  onNavigate?: () => void
}) {
  const view = useReaderUi((s) => s.view)
  const section = useReaderUi((s) => s.section)
  const selectView = useReaderUi((s) => s.selectView)
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectSection = useReaderUi((s) => s.selectSection)
  // 0014a Gate 1：桌面上下文（无 onNavigate = 桌面常驻栏；移动抽屉会在
  // 导航完成后回调关闭）才渲染「添加来源」按钮与共享 AddSourceDialog。
  const isDesktop = onNavigate === undefined
  const [addSourceOpen, setAddSourceOpen] = useState(false)

  return (
    <nav className="flex flex-col gap-1 p-2.5 max-lg:gap-1" aria-label="主导航">
      <SidebarHeader />
      {isDesktop && (
        <Suspense fallback={null}>
          <AddSourceDialog
            open={addSourceOpen}
            onClose={() => setAddSourceOpen(false)}
          />
        </Suspense>
      )}

      {/* F056 继续阅读（服务端跨设备；点击打开文章并定位段落） */}
      {isDesktop && <ContinueReadingCard />}
      {/* F057 最近打开（桌面折叠区；与移动端 RecentReads 共用真源） */}
      {isDesktop && <RecentReadsInline />}
      {/* N110 最近工作区（home 入口卡；device-local per-user 键） */}
      {isDesktop && (
        <Suspense fallback={null}>
          <RecentWorkspacesCard />
        </Suspense>
      )}

      {/* ===== 信息来源 ===== */}
      <div className="flex flex-col gap-0.5" role="group" aria-label="信息来源">
        <GroupLabel>信息来源</GroupLabel>

        {/* 全部信息源 + 「未读」过滤子项：并排不嵌套 button */}
        <div
          className={cx(
            'flex items-center gap-1 rounded-[var(--lumi-radius-md)]',
            view === 'all' || view === 'unread'
              ? 'bg-[var(--lumi-surface-selected)]'
              : 'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
          )}
        >
          <button
            type="button"
            onClick={() => {
              selectSection('home')
              selectScope(ALL_SCOPE)
              selectView('all')
              onNavigate?.()
            }}
            aria-current={view === 'all' ? 'true' : undefined}
            className={cx(
              'flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
              'min-h-8 py-1 max-lg:min-h-11 max-lg:items-center',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              view === 'all'
                ? 'font-medium text-[var(--lumi-accent-text)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
            )}
          >
            <Inbox aria-hidden className={icon16} />
            <span className="truncate">全部信息源</span>
          </button>
          <button
            type="button"
            onClick={() => {
              selectSection('home')
              selectView('unread')
              onNavigate?.()
            }}
            aria-pressed={view === 'unread'}
            className={cx(
              'mr-1.5 shrink-0 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px]',
              'min-h-6 transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              view === 'unread'
                ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                // 未激活 chip 可能落在选中分组表面上；tertiary 在该表面上
                // 对比度 4.43:1 不满足 WCAG AA → 用 secondary
                : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            未读
          </button>
        </div>

        <RssTree
          onNavigate={onNavigate}
          onAddSource={isDesktop ? () => setAddSourceOpen(true) : undefined}
        />

        {/* P04：统一来源页（GET /api/v1/sources 的分组总览 + 管理深链）。
            RSS 订阅行保留在上（scope 直达 + 分类树），订阅中心 section
            仍可从来源页 RSS 组深链进入。 */}
        <NavItem
          active={section === 'sources'}
          onClick={() => {
            selectSection('sources')
            onNavigate?.()
          }}
        >
          <Layers aria-hidden className={icon16} />
          来源
        </NavItem>

        {/* phase2 M1：书签（library 域）已可用——section 导航，替代原
            Phase 2 禁用占位（保持同位置，信息来源组内）。
            phase2 Gate 3：网页剪藏 / 网页快照同样激活为 section 导航。 */}
        <div className="mt-1 flex flex-col gap-0.5">
          <NavItem
            active={section === 'bookmarks'}
            onClick={() => {
              selectSection('bookmarks')
              onNavigate?.()
            }}
          >
            <Bookmark aria-hidden className={icon16} />
            书签
          </NavItem>
          <NavItem
            active={section === 'clips'}
            onClick={() => {
              selectSection('clips')
              onNavigate?.()
            }}
          >
            <Globe aria-hidden className={icon16} />
            网页剪藏
          </NavItem>
          <NavItem
            active={section === 'snapshots'}
            onClick={() => {
              selectSection('snapshots')
              onNavigate?.()
            }}
          >
            <Link2 aria-hidden className={icon16} />
            网页快照
          </NavItem>
          {/* 0021：收件箱（推送式来源）已可用——section 导航。 */}
          <NavItem
            active={section === 'inbox'}
            onClick={() => {
              selectSection('inbox')
              onNavigate?.()
            }}
          >
            <Archive aria-hidden className={icon16} />
            收件箱
          </NavItem>
          {/* P0-12：API 来源 / 邮件简报已是真实可用能力（Settings 的
              ApiSourcesSection / MailSection）——导航不再是 PlannedItem，
              而是真实入口：打开设置壳并直达对应分类。 */}
          <NavItem
            active={false}
            onClick={() => {
              requestOpenSettings('api-sources')
              onNavigate?.()
            }}
          >
            <FileText aria-hidden className={icon16} />
            API 来源
          </NavItem>
          <NavItem
            active={false}
            onClick={() => {
              requestOpenSettings('mail')
              onNavigate?.()
            }}
          >
            <Mail aria-hidden className={icon16} />
            邮件简报
          </NavItem>
          {/* phase2 G6：Obsidian 库（只读投影）已可用——section 导航。 */}
          <NavItem
            active={section === 'obsidian'}
            onClick={() => {
              selectSection('obsidian')
              onNavigate?.()
            }}
          >
            <FileText aria-hidden className={icon16} />
            Obsidian 库
          </NavItem>
        </div>
      </div>

      {/* ===== 工作区（稍后读 / 收藏——工作区为全局视图，scope 重置为全部） ===== */}
      <div className="mt-2 flex flex-col gap-0.5" role="group" aria-label="工作区">
        <GroupLabel>工作区</GroupLabel>

        <NavItem
          active={view === 'read-later'}
          onClick={() => {
            selectSection('home')
            selectScope(ALL_SCOPE)
            selectView('read-later')
            onNavigate?.()
          }}
        >
          <Clock aria-hidden className={icon16} />
          稍后读
        </NavItem>

        <NavItem
          active={view === 'starred'}
          onClick={() => {
            selectSection('home')
            selectScope(ALL_SCOPE)
            selectView('starred')
            onNavigate?.()
          }}
        >
          <Star aria-hidden className={icon16} />
          收藏
        </NavItem>

        {/* 0022：全局搜索（section=search；桌面渲染在 Timeline 列位） */}
        <NavItem
          active={section === 'search'}
          onClick={() => {
            selectSection('search')
            onNavigate?.()
          }}
        >
          <SearchIcon aria-hidden className={icon16} />
          搜索
        </NavItem>

        {/* phase2 M1：工作区列表页（section=workspaces；桌面 Timeline 列位） */}
        <NavItem
          active={section === 'workspaces'}
          onClick={() => {
            selectSection('workspaces')
            onNavigate?.()
          }}
        >
          <FolderOpen aria-hidden className={icon16} />
          工作区
        </NavItem>

        <div className="mt-1 flex flex-col gap-0.5">
          {/* phase2 G7：Agent 工作台已可用——section 导航。 */}
          <NavItem
            active={section === 'agent'}
            onClick={() => {
              selectSection('agent')
              onNavigate?.()
            }}
          >
            <Bot aria-hidden className={icon16} />
            Agent 工作台
          </NavItem>
          {/* P0-12 + Q-P2-24：RAG 管理入口已落地（设置 → AI 的
              RagSettingsSection）——导航不再说「独立管理入口尚未提供」
              （文案漂移回潮），直达该分类。 */}
          <NavItem
            active={false}
            onClick={() => {
              requestOpenSettings('ai')
              onNavigate?.()
            }}
          >
            <Zap aria-hidden className={icon16} />
            RAG 索引
          </NavItem>
          {/* phase2 G8：标签 / 图谱已可用——section 导航。 */}
          <NavItem
            active={section === 'graph'}
            onClick={() => {
              selectSection('graph')
              onNavigate?.()
            }}
          >
            <Tags aria-hidden className={icon16} />
            标签 / 图谱
          </NavItem>
        </div>
      </div>

      {/* 0067 多账户：当前身份 + 账号菜单（basic 模式零渲染，现状兼容） */}
      <AccountMenu />
    </nav>
  )
}

export default memo(Sidebar)

/** F035：单个固定视图行（实时计数徽标；失败态诚实显示 '—' 而非 0）。 */
function PinnedViewRow({ id, name }: { id: string; name: string }) {
  const count = usePinnedViewCount(id)
  const label =
    count.isPending || count.isError || (count.data?.error ?? null) !== null
      ? '—'
      : String(count.data?.count ?? 0)
  return (
    <button
      type="button"
      data-lumi-pinned-view=""
      onClick={() => {
        window.dispatchEvent(new CustomEvent('lumirss-navigate-search'))
      }}
      className={cx(
        'flex min-h-8 w-full items-center gap-2 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
        'py-1 transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] max-lg:min-h-11',
      )}
    >
      <span className="min-w-0 flex-1 truncate">{name}</span>
      <span
        className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 text-[11px] text-[var(--lumi-text-tertiary)]"
        data-lumi-pinned-count=""
      >
        {label}
      </span>
    </button>
  )
}

/** F035：固定视图块（无固定视图时零渲染）。 */
function PinnedViewsBlock() {
  const pinned = usePinnedViews()
  if (pinned.isPending || pinned.isError) return null
  const items = pinned.data?.items ?? []
  if (items.length === 0) return null
  return (
    <div className="mt-1 flex flex-col gap-0.5" data-lumi-pinned-views="">
      <p className="px-2.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        固定视图
      </p>
      {items.map((view) => (
        <PinnedViewRow key={view.id} id={view.id} name={view.name} />
      ))}
    </div>
  )
}
