/** F016 双篇对照 —— 恰好选中 2 条时的并排阅读（桌面）/ A·B 切换（移动）。
 *
 * 复用现有 Reader 的安全渲染层（ArticleContent：DOMPurify 唯一注入点），
 * 不复制任何 HTML 渲染实现；桌面两实例独立滚动；移动端 A/B 切换条保留
 * 各自滚动位置；关闭恢复原列表并移除本面板创建的两条详情查询缓存。 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEntryDetail } from '../api/queries'
import { useIsMobile } from '../lib/use-is-mobile'
import ArticleContent from './ArticleContent'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

function ComparePane({
  entryRef,
  active,
}: {
  entryRef: string
  active: boolean
}) {
  const detail = useEntryDetail(entryRef)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  if (detail.isPending) {
    return (
      <div
        data-testid={`compare-pane-${entryRef}`}
        className={cx('min-w-0 flex-1 overflow-y-auto p-4', !active && 'hidden')}
      >
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-2 h-40 w-full" />
      </div>
    )
  }
  if (detail.isError) {
    return (
      <div
        data-testid={`compare-pane-${entryRef}`}
        className={cx('min-w-0 flex-1 p-4', !active && 'hidden')}
      >
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          这一篇加载失败：{detail.error instanceof Error ? detail.error.message : '请重试。'}
        </p>
      </div>
    )
  }
  return (
    <div
      ref={scrollRef}
      data-testid={`compare-pane-${entryRef}`}
      data-compare-scroll=""
      className={cx(
        'min-w-0 flex-1 overflow-y-auto px-4 py-3',
        // 移动端 A/B 切换：隐藏非活动侧（display:none 保留其滚动位置）
        !active && 'hidden',
      )}
    >
      {detail.data !== undefined && <ArticleContent detail={detail.data} />}
    </div>
  )
}

export default function CompareRead({
  refs,
  onClose,
}: {
  refs: [string, string]
  onClose: () => void
}) {
  const isMobile = useIsMobile()
  const [a, b] = refs
  const [activeSide, setActiveSide] = useState<'a' | 'b'>('a')
  const queryClient = useQueryClient()

  // 关闭清理：移除本面板引入的两条详情缓存（避免对照打开的大正文
  // 长期占用内存；常规 Reader 的缓存策略不受影响）。
  useEffect(() => {
    return () => {
      queryClient.removeQueries({ queryKey: ['entry', a] })
      queryClient.removeQueries({ queryKey: ['entry', b] })
    }
  }, [a, b, queryClient])

  return (
    <section
      aria-label="对照阅读"
      data-testid="compare-read"
      className="flex h-full min-h-0 flex-col"
    >
      <div className="flex items-center gap-2 border-b border-[var(--lumi-border)] px-3 py-1.5">
        {isMobile ? (
          <div className="flex gap-1" role="tablist" aria-label="对照切换">
            <Button
              size="sm"
              variant={activeSide === 'a' ? 'primary' : 'ghost'}
              aria-pressed={activeSide === 'a'}
              onClick={() => setActiveSide('a')}
            >
              A 篇
            </Button>
            <Button
              size="sm"
              variant={activeSide === 'b' ? 'primary' : 'ghost'}
              aria-pressed={activeSide === 'b'}
              onClick={() => setActiveSide('b')}
            >
              B 篇
            </Button>
          </div>
        ) : (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            对照阅读（两篇独立滚动；关闭恢复原列表）
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          aria-label="关闭对照阅读"
          onClick={onClose}
          className="flex min-h-11 min-w-11 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>
      <div
        className={cx(
          'min-h-0 flex-1',
          isMobile ? 'flex' : 'grid grid-cols-2 divide-x divide-[var(--lumi-separator)]',
        )}
      >
        <ComparePane entryRef={a} active={!isMobile || activeSide === 'a'} />
        <ComparePane entryRef={b} active={!isMobile || activeSide === 'b'} />
      </div>
    </section>
  )
}
