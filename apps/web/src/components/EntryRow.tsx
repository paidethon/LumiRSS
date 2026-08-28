import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatPublishedAt(value: string | null): string {
  if (value === null) {
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

export default function EntryRow({
  item,
  selected,
}: {
  item: EntryListItem
  selected: boolean
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)

  return (
    <button
      type="button"
      onClick={() => selectEntry(item.entryRef)}
      aria-pressed={selected}
      className={`block w-full border-l-2 px-4 py-3 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--accent)] ${
        selected
          ? 'border-l-[var(--accent)] bg-blue-50/60'
          : 'border-l-transparent hover:bg-gray-50'
      }`}
    >
      <div className="flex items-center gap-2">
        {!item.read && (
          <span
            className="inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--accent)]"
            aria-label="未读"
          />
        )}
        {/* 0007：手机上标题必须 wrap（最多 3 行），不能一行截到看不懂；
            桌面保持单行 truncate */}
        <span
          className={`min-w-0 flex-1 text-sm max-lg:line-clamp-3 lg:truncate ${
            item.read ? 'font-normal text-[var(--text-muted)]' : 'font-medium text-[var(--text)]'
          }`}
          title={item.title}
        >
          {item.title}
        </span>
        {item.starred && (
          <span className="shrink-0 text-sm text-amber-500" aria-label="已收藏">
            ★
          </span>
        )}
      </div>
      {/* 0007：手机上 metadata 更紧凑（次要信息密度降低） */}
      <p className="mt-1 truncate text-xs text-[var(--text-muted)] max-lg:mt-0.5">
        {item.feedTitle}
        {item.author !== null && <span> · {item.author}</span>}
        <span> · {formatPublishedAt(item.publishedAt)}</span>
      </p>
    </button>
  )
}
