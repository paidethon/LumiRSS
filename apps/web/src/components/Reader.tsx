import { useEffect, useRef } from 'react'
import { useEntryDetail } from '../api/queries'
import { ApiError } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import ArticleContent from './ArticleContent'
import ReaderHeader from './ReaderHeader'
import ReaderPlaceholder from './ReaderPlaceholder'

/** Reader — 右栏状态机（0006）：
 *
 *   no selection → ReaderPlaceholder（不发 Detail 请求）
 *   pending      → Reader skeleton（Sidebar / EntryList 不受影响）
 *   404          → 「这篇文章已经不存在或不可用了。」+ 返回文章列表
 *   其它 error   → 「文章加载失败」+ 安全错误信息 + 重试
 *   success      → ReaderHeader（key=entryRef，防止旧 mutation UI 泄漏到
 *                  新 Entry）+ ArticleContent
 *
 * Reader 自己滚动；切换选择时滚回文章顶部。 */
export default function Reader() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const { data, isPending, isError, error, refetch } = useEntryDetail(selectedEntryRef)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    // 选择新文章时回到顶部（不建 scroll restoration 框架）；
    // scrollTop 赋值而非 scrollTo()，兼容 jsdom。
    if (scrollRef.current !== null) {
      scrollRef.current.scrollTop = 0
    }
  }, [selectedEntryRef])

  if (selectedEntryRef === null) {
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto">
        <ReaderPlaceholder />
      </div>
    )
  }

  if (isPending) {
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto">
        <div className="mx-auto flex max-w-[44rem] flex-col gap-3 p-8" aria-label="文章加载中">
          <div className="h-7 w-3/4 animate-pulse rounded bg-gray-100" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-gray-100" />
          <div className="h-8 w-40 animate-pulse rounded bg-gray-100" />
          <div className="mt-4 h-4 w-full animate-pulse rounded bg-gray-100" />
          <div className="h-4 w-11/12 animate-pulse rounded bg-gray-100" />
          <div className="h-4 w-10/12 animate-pulse rounded bg-gray-100" />
          <div className="h-4 w-full animate-pulse rounded bg-gray-100" />
        </div>
      </div>
    )
  }

  if (isError) {
    const isNotFound =
      error instanceof ApiError && error.status === 404
    if (isNotFound) {
      return (
        <div ref={scrollRef} className="h-full overflow-y-auto">
          <div className="flex h-full items-center justify-center p-8">
            <div className="max-w-sm text-center">
              <p className="text-base font-medium text-[var(--text)]">
                这篇文章已经不存在或不可用了。
              </p>
              <button
                type="button"
                onClick={() => selectEntry(null)}
                className="mt-4 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
              >
                返回文章列表
              </button>
            </div>
          </div>
        </div>
      )
    }
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto">
        <div className="flex h-full items-center justify-center p-8">
          <div className="max-w-sm text-center" role="alert">
            <p className="text-base font-medium text-[var(--text)]">文章加载失败</p>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {error instanceof Error ? error.message : '请稍后重试。'}
            </p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-4 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              重试
            </button>
          </div>
        </div>
      </div>
    )
  }

  const detail = data
  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <article className="mx-auto max-w-[44rem] px-8 py-6">
        {/* key=entryRef：切换 Entry = 组件重挂载，旧 mutation 的
            pending / error UI 不泄漏到新 Entry。 */}
        <ReaderHeader key={detail.entryRef} detail={detail} />
        <div className="pt-6">
          <ArticleContent detail={detail} />
        </div>
      </article>
    </div>
  )
}
