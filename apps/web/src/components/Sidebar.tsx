import {
  Bookmark,
  Bot,
  ChevronDown,
  FileText,
  Globe,
  Inbox,
  Link2,
  Mail,
  Rss,
  Star,
  Tags,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { useFeeds } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'
import { Skeleton } from './ui/Skeleton'
import SidebarHeader from './SidebarHeader'
import { cx } from './ui/cx'

/** Sidebar — 信息架构分组导航（0011 Gate 1/2 演进）。
 *
 * 两组结构（0010 Gate C 图 2 映射，0011 修订）：
 *   信息来源：全部信息流（可用）/ RSS 订阅（disclosure，默认收起）
 *            + Phase 2 项（网页剪藏/快照/API 来源/邮件/书签/Obsidian，禁用+徽标）
 *   工作区：  时间线 / 收藏（0011 去重：去掉「ME 时间线 ·」冗余前缀；
 *            未读作为时间线的过滤子项——与 view='unread' 语义一致）
 *
 * 0011 变更：
 * - 品牌区拆出 SidebarHeader（设置按钮移至右上角，底部设置行删除）；
 * - RSS 订阅改为 disclosure（新会话默认收起，aria-expanded/controls +
 *   可见 chevron）——Feed 契约无分类字段，展开后为单一「未分组」组；
 * - 选中 feed 后切回首页（section=home）+ 关闭移动抽屉（onNavigate）。
 *
 * 诚实原则：Phase 2 项可见但 disabled + 徽标——路线图可视化，非假控件。 */

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
          ? 'bg-[var(--lumi-surface-selected)] font-medium text-[var(--lumi-accent)]'
          : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
      )}
    >
      {children}
    </button>
  )
}

/** Phase 2 禁用项：可见 + 徽标 + 说明（不可点击） */
function PlannedItem({
  icon,
  label,
}: {
  icon: React.ReactNode
  label: string
}) {
  return (
    <div
      aria-disabled="true"
      title="Phase 2 功能（MVP 之后规划），当前不可用"
      className={cx(
        'flex w-full cursor-default items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1 text-left text-sm',
        'min-h-8 max-lg:min-h-11',
        'text-[var(--lumi-text-tertiary)] opacity-70',
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
      <span className="ml-auto shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] font-medium">
        Phase 2
      </span>
    </div>
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

/** RSS 订阅 disclosure（0011 Gate 2：默认收起，点击展开）。
 *
 * Feed 契约无分类字段——展开后为单一真实「未分组」组，禁止编造
 * 「设计/AI」等生产分类（契约缺口已记录给 0013）。 */
function RssDisclosure({
  expanded,
  onToggle,
  onNavigate,
}: {
  expanded: boolean
  onToggle: () => void
  onNavigate?: () => void
}) {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectView = useReaderUi((s) => s.selectView)
  const selectFeed = useReaderUi((s) => s.selectFeed)
  const selectSection = useReaderUi((s) => s.selectSection)
  const feeds = useFeeds()

  const anyFeedActive = selectedFeedUrl !== null

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls="sidebar-rss-feeds"
        className={cx(
          'flex w-full items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
          'min-h-8 py-1 max-lg:min-h-11 max-lg:items-center',
          'transition-colors duration-[var(--lumi-motion-fast)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          anyFeedActive && view === 'all'
            ? 'bg-[var(--lumi-surface-selected)] font-medium text-[var(--lumi-accent)]'
            : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
        )}
      >
        <Rss aria-hidden className={icon16} />
        <span className="truncate">RSS 订阅</span>
        <ChevronDown
          aria-hidden
          className={cx('ml-auto size-4 shrink-0 transition-transform duration-[var(--lumi-motion-fast)]', expanded && 'rotate-180')}
        />
      </button>

      {expanded && (
        <div id="sidebar-rss-feeds" className="flex flex-col gap-0.5 pl-2.5">
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
            <p className="px-2.5 py-2 text-xs text-[var(--lumi-text-tertiary)]">
              未分组 · 暂无订阅
            </p>
          )}

          {feeds.data?.map((feed) => (
            <NavItem
              key={feed.feedUrl}
              active={selectedFeedUrl === feed.feedUrl}
              onClick={() => {
                // 选中 feed：切回首页 + 更新 scope（onNavigate 关移动抽屉）
                selectSection('home')
                selectView('all')
                selectFeed(feed.feedUrl)
                onNavigate?.()
              }}
            >
              <span
                aria-hidden="true"
                className="size-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: feedColor(feed.feedUrl) }}
              />
              <span className="truncate" title={feed.title}>
                {feed.title}
              </span>
            </NavItem>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Sidebar({
  onNavigate,
}: {
  onNavigate?: () => void
}) {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectView = useReaderUi((s) => s.selectView)
  const selectFeed = useReaderUi((s) => s.selectFeed)
  const selectSection = useReaderUi((s) => s.selectSection)

  // RSS disclosure：新会话默认收起（0011 Spec §设计规格）
  const [rssExpanded, setRssExpanded] = useState(false)

  return (
    <nav className="flex flex-col gap-1 p-2.5 max-lg:gap-1" aria-label="主导航">
      <SidebarHeader />

      {/* ===== 信息来源 ===== */}
      <div className="flex flex-col gap-0.5" role="group" aria-label="信息来源">
        <GroupLabel>信息来源</GroupLabel>

        <NavItem
          active={view === 'all' && selectedFeedUrl === null}
          onClick={() => {
            selectSection('home')
            selectView('all')
            selectFeed(null)
            onNavigate?.()
          }}
        >
          <Inbox aria-hidden className={icon16} />
          全部信息流
        </NavItem>

        <RssDisclosure
          expanded={rssExpanded}
          onToggle={() => setRssExpanded((v) => !v)}
          onNavigate={onNavigate}
        />

        {/* Phase 2 信息来源项（可见禁用） */}
        <div className="mt-1 flex flex-col gap-0.5">
          <PlannedItem icon={<Globe aria-hidden className={icon16} />} label="网页剪藏" />
          <PlannedItem icon={<Link2 aria-hidden className={icon16} />} label="网页快照" />
          <PlannedItem icon={<FileText aria-hidden className={icon16} />} label="API 来源" />
          <PlannedItem icon={<Mail aria-hidden className={icon16} />} label="邮件简报" />
          <PlannedItem icon={<Bookmark aria-hidden className={icon16} />} label="书签" />
          <PlannedItem icon={<FileText aria-hidden className={icon16} />} label="Obsidian 库" />
        </div>
      </div>

      {/* ===== 工作区（0011 去重：时间线 / 收藏；未读为时间线过滤子项） ===== */}
      <div className="mt-2 flex flex-col gap-0.5" role="group" aria-label="工作区">
        <GroupLabel>工作区</GroupLabel>

        {/* 时间线行：主按钮 + 「未读」过滤子项（用户决策 4）并排，
            避免嵌套 button（无效 HTML） */}
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
              selectView('all')
              selectFeed(null)
              onNavigate?.()
            }}
            aria-current={view === 'all' ? 'true' : undefined}
            className={cx(
              'flex min-w-0 flex-1 items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
              'min-h-8 py-1 max-lg:min-h-11 max-lg:items-center',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              view === 'all'
                ? 'font-medium text-[var(--lumi-accent)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
            )}
          >
            <Inbox aria-hidden className={icon16} />
            <span className="truncate">时间线</span>
          </button>
          <button
            type="button"
            onClick={() => {
              selectSection('home')
              selectView('unread')
              selectFeed(null)
              onNavigate?.()
            }}
            aria-pressed={view === 'unread'}
            className={cx(
              'mr-1.5 shrink-0 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px]',
              'min-h-6 transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              view === 'unread'
                ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent)]'
                : 'text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            未读
          </button>
        </div>

        <NavItem
          active={view === 'starred'}
          onClick={() => {
            selectSection('home')
            selectView('starred')
            selectFeed(null)
            onNavigate?.()
          }}
        >
          <Star aria-hidden className={icon16} />
          收藏
        </NavItem>

        <div className="mt-1 flex flex-col gap-0.5">
          <PlannedItem icon={<Bot aria-hidden className={icon16} />} label="Agent 工作台" />
          <PlannedItem icon={<Zap aria-hidden className={icon16} />} label="RAG 索引" />
          <PlannedItem icon={<Tags aria-hidden className={icon16} />} label="标签 / 图谱" />
        </div>
      </div>
    </nav>
  )
}
