import { useEntries } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'

/** 0005 的右栏只是占位区：显示选中文章的 title/feedTitle，
 * 数据从当前 TanStack Query 的 pages 里 find（不复制进 Zustand，
 * 也不调用 detail API——那是 0006 Reader 的事）。 */
export default function ReaderPlaceholder() {
  const view = useReaderUi((s) => s.view)
  const selectedFeedUrl = useReaderUi((s) => s.selectedFeedUrl)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)

  const { data } = useEntries(view, selectedFeedUrl)
  const entries = data?.pages.flatMap((page) => page.items) ?? []
  const selected = selectedEntryRef === null
    ? undefined
    : entries.find((item) => item.entryRef === selectedEntryRef)

  if (selected === undefined) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <p className="text-base font-medium text-[var(--text)]">
            选择一篇文章开始阅读
          </p>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            这里将在下一个里程碑（0006 — Reader）展示文章正文。
          </p>
        </div>
      </div>
    )
  }

  return (
    <article className="mx-auto max-w-2xl p-8" aria-label="已选文章概要">
      <h2 className="text-xl font-semibold leading-snug text-[var(--text)]">
        {selected.title}
      </h2>
      <p className="mt-2 text-sm text-[var(--text-muted)]">
        {selected.feedTitle}
        {selected.author !== null && <span> · {selected.author}</span>}
      </p>
      <p className="mt-8 text-sm text-[var(--text-muted)]">
        正文阅读将在 0006 — Reader 中实现。
      </p>
    </article>
  )
}
