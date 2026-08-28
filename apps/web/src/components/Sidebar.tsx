import { useFeeds } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'
import type { EntryView } from '../api/types'

const VIEW_LABELS: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

function NavButton({
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
      className={`w-full rounded-md border px-3 py-1.5 text-left text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] max-lg:min-h-11 ${
        active
          ? 'border-[var(--accent)] bg-blue-50 font-medium text-[var(--accent)]'
          : 'border-transparent text-[var(--text)] hover:bg-gray-100'
      }`}
    >
      {children}
    </button>
  )
}

/** Sidebar — 导航（视图 + 订阅）。
 *
 * 可选 onNavigate：仅在真正完成一次导航选择（view / feed）后回调。
 * Desktop 挂载时不传（行为不变）；移动端 Drawer 传
 * closeMobileSidebar，用于导航后关闭抽屉。非导航按钮（如订阅加载
 * 失败的「重试」）不触发。 */
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

  return (
    <nav className="flex flex-col gap-4 p-3 max-lg:gap-1" aria-label="主导航">
      <div className="px-2 pt-1">
        <h1 className="text-lg font-semibold tracking-tight text-[var(--text)]">
          LumiRSS
        </h1>
        <p className="text-xs text-[var(--text-muted)]">流光阅源</p>
      </div>

      <div className="flex flex-col gap-1" role="group" aria-label="视图">
        {(Object.keys(VIEW_LABELS) as EntryView[]).map((v) => (
          <NavButton
            key={v}
            active={view === v}
            onClick={() => {
              selectView(v)
              onNavigate?.()
            }}
          >
            {VIEW_LABELS[v]}
          </NavButton>
        ))}
      </div>

      <div className="flex flex-col gap-1" role="group" aria-label="订阅">
        <p className="px-2 pb-1 text-xs font-medium text-[var(--text-muted)]">
          Feeds
        </p>

        <NavButton
          active={selectedFeedUrl === null}
          onClick={() => {
            selectFeed(null)
            onNavigate?.()
          }}
        >
          All Feeds
        </NavButton>

        {feeds.isPending && (
          <div className="flex flex-col gap-1 px-2 pt-1" aria-label="订阅加载中">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-6 animate-pulse rounded bg-gray-100" />
            ))}
          </div>
        )}

        {feeds.isError && (
          <div className="px-2 py-2 text-sm text-red-600">
            <p>订阅加载失败</p>
            <button
              type="button"
              onClick={() => feeds.refetch()}
              className="mt-1 rounded border border-gray-300 px-2 py-0.5 text-xs hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              重试
            </button>
          </div>
        )}

        {feeds.data?.map((feed) => (
          <NavButton
            key={feed.feedUrl}
            active={selectedFeedUrl === feed.feedUrl}
            onClick={() => {
              selectFeed(feed.feedUrl)
              onNavigate?.()
            }}
          >
            <span className="block truncate" title={feed.title}>
              {feed.title}
            </span>
          </NavButton>
        ))}
      </div>
    </nav>
  )
}
