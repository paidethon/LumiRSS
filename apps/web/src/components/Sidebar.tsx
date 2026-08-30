import {
  Bookmark,
  Bot,
  FileText,
  Globe,
  Inbox,
  Link2,
  Mail,
  Rss,
  Settings,
  Star,
  Tags,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { useFeeds } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'
import type { EntryView } from '../api/types'
import { Skeleton } from './ui/Skeleton'
import SettingsModal from './settings/SettingsModal'
import { cx } from './ui/cx'

/** Sidebar — 信息架构分组导航（0010 Gate C，图 2 映射定稿）。
 *
 * 两组结构（Spec §设计规格）：
 *   信息来源：全部信息流（可用）/ RSS 订阅（可用，现有 feeds）
 *            + Phase 2 项（网页剪藏/快照/API 来源/邮件/书签/Obsidian，禁用+徽标）
 *   工作区：  ME 时间轴（Unread/Starred 视图迁入，可用）
 *            + Phase 2 项（Agent 工作台/RAG 索引/标签图谱，禁用）
 *            + 设置（可用，开 Modal）
 *
 * 诚实原则：Phase 2 项可见但 disabled + 徽标 + tooltip——这是路线图
 * 可视化，不是假控件（AC12/V8）。 */

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

export default function Sidebar({
  onNavigate,
}: {
  onNavigate?: () => void
}) {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectView = useReaderUi((s) => s.selectView)
  const selectFeed = useReaderUi((s) => s.selectFeed)

  const feeds = useFeeds()
  const [settingsOpen, setSettingsOpen] = useState(false)

  // ME 时间轴视图组（Unread/Starred 从原视图区迁入工作区组）
  const timelineViews: { key: EntryView; label: string; icon: React.ReactNode }[] = [
    { key: 'unread', label: '未读', icon: <FileText aria-hidden className={icon16} /> },
    { key: 'starred', label: '收藏', icon: <Star aria-hidden className={icon16} /> },
  ]

  return (
    <nav className="flex flex-col gap-1 p-2.5 max-lg:gap-1" aria-label="主导航">
      <div className="px-2.5 pb-1 pt-2">
        <h1 className="text-base font-semibold tracking-tight text-[var(--lumi-text-primary)]">
          LumiRSS
        </h1>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">流光阅源</p>
      </div>

      {/* ===== 信息来源 ===== */}
      <div className="flex flex-col gap-0.5" role="group" aria-label="信息来源">
        <GroupLabel>信息来源</GroupLabel>

        <NavItem
          active={view === 'all' && selectedFeedUrl === null}
          onClick={() => {
            selectView('all')
            selectFeed(null)
            onNavigate?.()
          }}
        >
          <Inbox aria-hidden className={icon16} />
          全部信息流
        </NavItem>

        {/* RSS 订阅（现有 feeds 列表） */}
        <NavItem
          active={selectedFeedUrl === null ? false : view === 'all'}
          onClick={() => {
            selectView('all')
            onNavigate?.()
          }}
        >
          <Rss aria-hidden className={icon16} />
          RSS 订阅
        </NavItem>

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

        {feeds.data?.map((feed) => (
          <NavItem
            key={feed.feedUrl}
            active={selectedFeedUrl === feed.feedUrl}
            onClick={() => {
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

      {/* ===== 工作区 ===== */}
      <div className="mt-2 flex flex-col gap-0.5" role="group" aria-label="工作区">
        <GroupLabel>工作区</GroupLabel>

        {timelineViews.map((v) => (
          <NavItem
            key={v.key}
            active={view === v.key}
            onClick={() => {
              selectView(v.key)
              selectFeed(null)
              onNavigate?.()
            }}
          >
            {v.icon}
            ME 时间线 · {v.label}
          </NavItem>
        ))}

        <div className="mt-1 flex flex-col gap-0.5">
          <PlannedItem icon={<Bot aria-hidden className={icon16} />} label="Agent 工作台" />
          <PlannedItem icon={<Zap aria-hidden className={icon16} />} label="RAG 索引" />
          <PlannedItem icon={<Tags aria-hidden className={icon16} />} label="标签 / 图谱" />
        </div>
      </div>

      {/* ===== 底部工具区 ===== */}
      <div className="mt-auto pt-2">
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className={cx(
            'flex w-full items-center gap-2.5 rounded-[var(--lumi-radius-md)] px-2.5 text-left text-sm',
            'min-h-8 py-1 max-lg:min-h-11',
            'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <Settings aria-hidden className={icon16} />
          设置
        </button>
      </div>

      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </nav>
  )
}
