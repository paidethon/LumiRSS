import { Inbox } from 'lucide-react'
import { useEntries } from '../api/queries'
import type { EntryView } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import EntryRow from './EntryRow'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

const VIEW_TITLES: Record<EntryView, string> = {
  all: 'All',
  unread: 'Unread',
  starred: 'Starred',
}

const EMPTY_TEXTS: Record<EntryView, { title: string; description: string }> = {
  all: { title: '这里还没有文章', description: '订阅源还没有内容，稍后再来看看。' },
  unread: { title: '没有未读文章', description: '全部读完了，干得漂亮。' },
  starred: { title: '还没有收藏文章', description: '阅读时点击「收藏」，文章会出现在这里。' },
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
      <header className="border-b border-[var(--lumi-separator)] px-4 py-2.5">
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
          {VIEW_TITLES[view]}
        </h2>
        <p className="text-xs text-[var(--lumi-text-tertiary)]">已加载 {entries.length} 条</p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isPending && (
          <div className="flex flex-col gap-3 p-4" aria-label="文章加载中">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex flex-col gap-1.5">
                <Skeleton className="h-3 w-2/5" />
                <Skeleton className="h-4 w-4/5" />
              </div>
            ))}
          </div>
        )}

        {isError && (
          <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
            <p>文章加载失败</p>
            <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{error.message}</p>
            <Button
              size="sm"
              onClick={() => refetch()}
              className="mt-2 max-lg:w-full"
            >
              重试
            </Button>
          </div>
        )}

        {!isPending && !isError && entries.length === 0 && (
          <EmptyState
            icon={<Inbox />}
            title={EMPTY_TEXTS[view].title}
            description={EMPTY_TEXTS[view].description}
            className="h-full"
          />
        )}

        {entries.length > 0 && (
          <ul className="divide-y divide-[var(--lumi-separator)]">
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
          className="border-t border-[var(--lumi-separator)] p-3"
          style={{ paddingBottom: 'max(0.75rem, var(--safe-bottom))' }}
        >
          {hasNextPage ? (
            <Button
              variant="ghost"
              disabled={isFetchingNextPage}
              onClick={() => fetchNextPage()}
              className="w-full border border-[var(--lumi-accent)] text-[var(--lumi-accent)] hover:bg-[var(--lumi-accent-soft)]"
            >
              {isFetchingNextPage ? '加载中…' : '加载更多'}
            </Button>
          ) : (
            <p className="text-center text-xs text-[var(--lumi-text-tertiary)]">已经到底了</p>
          )}
        </footer>
      )}
    </div>
  )
}
