import { useEntries } from '../api/queries'
import { useReaderUi } from '../store/reader-ui'

/** 0005 的右栏只是占位区：显示选中文章的 title/feedTitle，
 * 数据从当前 TanStack Query 的 pages 里 find（不复制进 Zustand，
 * 也不调用 detail API——那是 0006 Reader 的事）。 */
export default function ReaderPlaceholder() {
  const view = useReaderUi((s) => s.view)
  const scope = useReaderUi((s) => s.scope)
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)

  const { data } = useEntries(scope, view)
  const entries = data?.pages.flatMap((page) => page.items) ?? []
  const selected = selectedEntryRef === null
    ? undefined
    : entries.find((item) => item.entryRef === selectedEntryRef)

  if (selected === undefined) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <p className="text-base font-medium text-[var(--lumi-text-primary)]">
            选择一篇文章开始阅读
          </p>
          <p className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
            正文将在右侧展示；也可以用 ← 返回列表。
          </p>
        </div>
      </div>
    )
  }

  return (
    <article className="mx-auto max-w-[46rem] p-8 max-lg:px-5" aria-label="已选文章概要">
      <h2 className="text-xl font-semibold leading-snug text-[var(--lumi-text-primary)]">
        {selected.title}
      </h2>
      <p className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
        {selected.feedTitle}
        {selected.author !== null && <span> · {selected.author}</span>}
      </p>
      <p className="mt-8 text-sm text-[var(--lumi-text-secondary)]">
        正文加载中…
      </p>
    </article>
  )
}
