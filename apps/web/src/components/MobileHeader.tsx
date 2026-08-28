import { useFeeds } from '../api/queries'
import type { EntryView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const VIEW_LABELS: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

/** MobileHeader — <1024px 顶栏（0007）。
 *
 * 无选中：[☰] LumiRSS + 当前 scope（view 名或 feed 标题）；
 * 有选中：[← 返回] + scope（Reader 打开时不堆叠 Menu + Back + toolbar，
 * Read/Star 等操作仍在 ReaderHeader 正文区域）。
 *
 * 返回只做 selectEntry(null)：Entry List 的 TanStack Query cache
 * 仍在，直接恢复显示，不 reload、不重新 fetch。 */
export default function MobileHeader() {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const openMobileSidebar = useReaderUi((s) => s.openMobileSidebar)
  const mobileSidebarOpen = useReaderUi((s) => s.mobileSidebarOpen)
  const selectEntry = useReaderUi((s) => s.selectEntry)

  const feeds = useFeeds()
  const feedTitle =
    selectedFeedUrl === null
      ? null
      : (feeds.data?.find((feed) => feed.feedUrl === selectedFeedUrl)?.title ??
        null)
  const scopeTitle = feedTitle ?? VIEW_LABELS[view]

  return (
    <header
      className="flex min-h-11 items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-2 lg:hidden"
      style={{ paddingTop: 'var(--safe-top)' }}
    >
      {selectedEntryRef === null ? (
        <button
          type="button"
          onClick={openMobileSidebar}
          aria-expanded={mobileSidebarOpen}
          aria-controls="mobile-navigation-drawer"
          aria-label="打开导航"
          className="flex min-h-11 min-w-11 items-center justify-center rounded-md px-2 text-xl leading-none text-[var(--text)] transition-colors hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          ☰
        </button>
      ) : (
        <button
          type="button"
          onClick={() => selectEntry(null)}
          aria-label="返回文章列表"
          className="flex min-h-11 min-w-11 items-center justify-center rounded-md px-2 text-sm text-[var(--accent)] transition-colors hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          ← 返回
        </button>
      )}

      <div className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-[var(--text)]">
          {selectedEntryRef === null ? 'LumiRSS' : '阅读'}
        </span>
        <span className="block truncate text-xs text-[var(--text-muted)]">
          {scopeTitle}
        </span>
      </div>
    </header>
  )
}
