import { FileText, Inbox, Rss, Settings, Star } from 'lucide-react'
import { useState } from 'react'
import { useFeeds } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'
import type { EntryView } from '../api/types'
import { Skeleton } from './ui/Skeleton'
import SettingsDialog from './SettingsDialog'
import { cx } from './ui/cx'

const VIEW_LABELS: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

const VIEW_ICONS: Record<EntryView, React.ReactNode> = {
  all: <Inbox aria-hidden className="size-4 shrink-0" />,
  unread: <FileText aria-hidden className="size-4 shrink-0" />,
  starred: <Star aria-hidden className="size-4 shrink-0" />,
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

/** NavItem — Folo 密度（0009 Gate 2）：32px 行高、r-md(8px)、图标 + 文字，
 * 三态分离（hover=中性 surface、selected=selected surface + accent 文字、
 * focus=focus-ring）。选中态不用浓色大填充（Spec 组件状态规则）。 */
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

/** Sidebar — 导航（视图 + 订阅）。0009 Gate 2 视觉重建：
 *
 * - 品牌区：LumiRSS + 流光阅源（紧凑）；
 * - 视图区：lucide 图标 + 标签；
 * - 订阅区：分类色圆点（确定性哈希分配，仅点缀）+ 标题 truncate；
 * - 骨架屏用 Skeleton primitive（token 化）；
 * - 可选 onNavigate：仅在真正完成一次导航选择（view / feed）后回调
 *   （移动端 Drawer 用于关闭抽屉；Desktop 不传，行为不变）。 */
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

  return (
    <nav className="flex flex-col gap-3 p-2.5 max-lg:gap-1" aria-label="主导航">
      <div className="px-2.5 pb-1 pt-2">
        <h1 className="text-base font-semibold tracking-tight text-[var(--lumi-text-primary)]">
          LumiRSS
        </h1>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">流光阅源</p>
      </div>

      <div className="flex flex-col gap-0.5" role="group" aria-label="视图">
        {(Object.keys(VIEW_LABELS) as EntryView[]).map((v) => (
          <NavItem
            key={v}
            active={view === v}
            onClick={() => {
              selectView(v)
              onNavigate?.()
            }}
          >
            {VIEW_ICONS[v]}
            {VIEW_LABELS[v]}
          </NavItem>
        ))}
      </div>

      <div className="flex flex-col gap-0.5" role="group" aria-label="订阅">
        <p className="px-2.5 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
          Feeds
        </p>

        <NavItem
          active={selectedFeedUrl === null}
          onClick={() => {
            selectFeed(null)
            onNavigate?.()
          }}
        >
          <Rss aria-hidden className="size-4 shrink-0" />
          All Feeds
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
            {/* 分类色圆点：确定性哈希分配，仅 6px 点缀（Spec：分类色只用于小图标/圆点） */}
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

      {/* 底部工具区：设置（0009 Gate 4 入口，Appearance 真实可用）。
          mt-auto 把它钉在 Sidebar 底部（窄屏 feed 多时仍在末尾可达）。 */}
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
          <Settings aria-hidden className="size-4 shrink-0" />
          设置
        </button>
      </div>

      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </nav>
  )
}
