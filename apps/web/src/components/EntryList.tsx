import { useEntries } from '../api/queries'
import type { EntryView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import EntryRow from './EntryRow'

const VIEW_TITLES: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

const EMPTY_TEXTS: Record<EntryView, string> = {
  all: '这里还没有文章',
  unread: '没有未读文章',
  starred: '还没有收藏文章',
}

export default function EntryList() {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)

  const feedsTitle = useEntries(view, selectedFeedUrl)
  const { data, isPending, isError, error, refetch } = feedsTitle
  const entries = data?.pages.flatMap((page) => page.items) ?? []
  const hasNextPage = feedsTitle.hasNextPage
  const isFetchingNextPage = feedsTitle.isFetchingNextPage
  const fetchNextPage = feedsTitle.fetchNextPage

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-[var(--border)] px-4 py-3">
        <h2 className="text-sm font-semibold text-[var(--text)]">
          {VIEW_TITLES[view]}
        </h2>
        <p className="text-xs text-[var(--text-muted)]">已加载 {entries.length} 条</p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isPending && (
          <div className="flex flex-col gap-2 p-4" aria-label="文章加载中">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex flex-col gap-1">
                <div className="h-4 w-3/4 animate-pulse rounded bg-gray-100" />
                <div className="h-3 w-1/2 animate-pulse rounded bg-gray-100" />
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="p-4 text-sm text-red-600" role="alert">
            <p>文章加载失败</p>
            <p className="mt-1 text-xs">{error.message}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-2 min-h-11 rounded border border-gray-300 px-3 text-sm hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] max-lg:w-full"
            >
              重试
            </button>
          </div>
        )}

        {!isPending && !isError && entries.length === 0 && (
          <div className="flex h-full items-center justify-center p-8 text-sm text-[var(--text-muted)]">
            {EMPTY_TEXTS[view]}
          </div>
        )}

        {entries.length > 0 && (
          <ul className="divide-y divide-[var(--border)]">
            {entries.map((item) => (
              <li key={item.entryRef}>
                <EntryRow item={item} selected={item.entryRef === selectedEntryRef} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {!isPending && !isError && entries.length > 0 && (
        <footer
          className="border-t border-[var(--border)] p-3"
          style={{ paddingBottom: 'max(0.75rem, var(--safe-bottom))' }}
        >
          {hasNextPage ? (
            <button
              type="button"
              disabled={isFetchingNextPage}
              onClick={() => fetchNextPage()}
              className="min-h-11 w-full rounded-md border border-[var(--accent)] px-3 text-sm text-[var(--accent)] transition-colors hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              {isFetchingNextPage ? '加载中…' : '加载更多'}
            </button>
          ) : (
            <p className="text-center text-xs text-[var(--text-muted)]">已经到底了</p>
          )}
        </footer>
      )}
    </div>
  )
}
