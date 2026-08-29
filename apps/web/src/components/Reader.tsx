import { useEffect, useRef } from 'react'
import { RefreshCw } from 'lucide-react'
import { useEntryDetail } from '../api/queries'
import { ApiError } from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import ArticleContent from './ArticleContent'
import ReaderHeader from './ReaderHeader'
import ReaderPlaceholder from './ReaderPlaceholder'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'

/** Reader — 右栏状态机（0006 行为 / 0009 Gate 3 视觉重建）：
 *
 *   no selection → ReaderPlaceholder（不发 Detail 请求）
 *   pending      → Reader skeleton（Sidebar / EntryList 不受影响）
 *   404          → 「这篇文章已经不存在或不可用了。」+ 返回文章列表
 *   其它 error   → 「文章加载失败」+ 安全错误信息 + 重试
 *   success      → ReaderHeader（key=entryRef，防止旧 mutation UI 泄漏到
 *                  新 Entry）+ ArticleContent
 *
 * 0009 Gate 3：
 * - 容器背景用 --lumi-reader-bg（Reader 独立背景钩子，tokens.css 默认
 *   指向 --lumi-reader；App Theme 与 Reader Theme 分离的接线点）；
 * - 正文最大宽度 46rem（~736px，Spec 720–780 区间），居中；
 * - skeleton / error / 404 全部 token 化 + primitives。
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
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <ReaderPlaceholder />
      </div>
    )
  }

  if (isPending) {
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <div className="mx-auto flex max-w-[46rem] flex-col gap-3 p-8 max-lg:px-5" aria-label="文章加载中">
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-8 w-11/12" />
          <Skeleton className="h-8 w-3/4" />
          <div className="mt-4 flex flex-col gap-2.5">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-10/12" />
            <Skeleton className="h-4 w-full" />
          </div>
        </div>
      </div>
    )
  }

  if (isError) {
    const isNotFound =
      error instanceof ApiError && error.status === 404
    if (isNotFound) {
      return (
        <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
          <div className="flex h-full items-center justify-center p-8">
            <div className="max-w-sm text-center">
              <p className="text-base font-medium text-[var(--lumi-text-primary)]">
                这篇文章已经不存在或不可用了。
              </p>
              <Button
                variant="secondary"
                onClick={() => selectEntry(null)}
                className="mt-4"
              >
                返回文章列表
              </Button>
            </div>
          </div>
        </div>
      )
    }
    return (
      <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
        <div className="flex h-full items-center justify-center p-8">
          <div className="max-w-sm text-center" role="alert">
            <p className="text-base font-medium text-[var(--lumi-text-primary)]">文章加载失败</p>
            <p className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
              {error instanceof Error ? error.message : '请稍后重试。'}
            </p>
            <Button
              variant="secondary"
              onClick={() => refetch()}
              className="mt-4"
            >
              <RefreshCw aria-hidden className="size-3.5" />
              重试
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const detail = data
  return (
    <div ref={scrollRef} className="h-full overflow-y-auto bg-[var(--lumi-reader-bg)]">
      {/* 0009 Gate 3：正文宽度 46rem（~736px，Spec 720–780 区间）；
          0007 语义保留：手机左右留白收紧（max-lg:px-5），底部计入 safe area */}
      <article
        className="mx-auto max-w-[46rem] px-8 py-6 max-lg:px-5"
        style={{ paddingBottom: 'max(1.5rem, var(--safe-bottom))' }}
      >
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
