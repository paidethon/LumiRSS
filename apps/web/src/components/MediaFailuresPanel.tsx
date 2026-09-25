/** N039 失效附件面板（Reader 内挂载）。
 *
 * - 检测：在正文容器上挂 capture 阶段 error 监听（img 的 error 不冒泡，
 *   capture 在容器上可截获）→ POST /entries/{ref}/media-failures 上报
 *   （服务端幂等 upsert，≤50 条/条目）；
 * - 呈现：失效附件列表（kind/src/最近上报）；
 * - 单项重新加载：对匹配 src 的正文 img 做**一次性** cache-bust（追加
 *   lumi-rb 参数）；已重载的项立即禁用——本面板没有任何自动重试循环，
 *   重复加载需要用户再次显式点击（且每次只 bust 一次）。
 */

import { useEffect, useRef, useState } from 'react'
import { ImageOff, Loader2, RefreshCw } from 'lucide-react'
import {
  useMediaFailures,
  useReportMediaFailureMutation,
} from '../api/queries'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'

/** 已做一次性 cache-bust 的 src 集合（组件级；重载按钮置灰的依据）。 */
const reloadedSrcs = new Set<string>()

function bustSrcOnce(src: string): string {
  const sep = src.includes('?') ? '&' : '?'
  return `${src}${sep}lumi-rb=${Date.now().toString(36)}`
}

export function MediaFailuresPanel({ entryRef }: { entryRef: string | null }) {
  const failuresQuery = useMediaFailures(entryRef)
  const reportMutation = useReportMediaFailureMutation()
  const [open, setOpen] = useState(false)
  // 防抖：同一 src 的一次上报在途时不重复上报（服务端本就幂等，这里
  // 只是省流量）。
  const inFlight = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (entryRef === null) return
    const container = document.querySelector('.lumi-reader-article')
    if (container === null) return
    const onError = (event: Event) => {
      const target = event.target
      if (!(target instanceof HTMLImageElement)) return
      const src = target.getAttribute('src')
      if (src === null || src === '' || src.startsWith('data:')) return
      if (inFlight.current.has(src)) return
      inFlight.current.add(src)
      reportMutation.mutate(
        { entryRef, failures: [{ kind: 'image', src }] },
        { onSettled: () => inFlight.current.delete(src) },
      )
    }
    container.addEventListener('error', onError, true)
    return () => container.removeEventListener('error', onError, true)
  }, [entryRef, reportMutation])

  if (entryRef === null) return null
  const failures = failuresQuery.data?.failures ?? []

  return (
    <div
      className="mt-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-xs"
      data-testid="media-failures-panel"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-7 w-full items-center gap-1.5 rounded px-1 text-left text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        <ImageOff aria-hidden className="size-3.5" />
        失效附件
        {failures.length > 0 && (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-danger)] px-1.5 text-[10px] text-white">
            {failures.length}
          </span>
        )}
        <span className="flex-1" />
        <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
          {open ? '收起' : '展开'}
        </span>
      </button>
      {open && (
        <>
          {failuresQuery.isPending ? (
            <p className="flex items-center gap-1.5 px-1 py-1 text-[var(--lumi-text-tertiary)]">
              <Loader2 aria-hidden className="size-3 animate-spin" /> 加载中…
            </p>
          ) : failuresQuery.isError ? (
            <EmptyState icon={<ImageOff aria-hidden className="size-5" />} title="加载失败" description="请稍后重试。" />
          ) : failures.length === 0 ? (
            <p className="px-1 py-1 text-[10px] text-[var(--lumi-text-tertiary)]">
              暂无失效记录；正文图片加载失败会自动记在这里（只记录，不自动重试）。
            </p>
          ) : (
            <ul className="mt-1 space-y-1">
              {failures.map((failure) => {
                const reloaded = reloadedSrcs.has(failure.src)
                return (
                  <li
                    key={`${failure.kind}-${failure.src}`}
                    className="flex items-center gap-1.5 rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] px-1.5 py-1"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[var(--lumi-text-primary)]">{failure.src}</span>
                      <span className="block text-[10px] text-[var(--lumi-text-tertiary)]">
                        {failure.kind} · 上报 {failure.hitCount} 次 · 最近 {failure.lastSeenAt.slice(5, 16).replace('T', ' ')}
                      </span>
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={reloaded}
                      onClick={() => {
                        // 单项重新加载：一次性 cache-bust（仅此一次；无
                        // 自动重试——按钮即禁用）。
                        const article = document.querySelector('.lumi-reader-article')
                        if (article === null) return
                        for (const img of article.querySelectorAll<HTMLImageElement>('img')) {
                          const current = img.getAttribute('src')
                          if (current === failure.src) {
                            const next = bustSrcOnce(failure.src)
                            img.setAttribute('src', next)
                            reloadedSrcs.add(failure.src)
                            break
                          }
                        }
                      }}
                    >
                      <RefreshCw aria-hidden className="size-3" />
                      {reloaded ? '已重载' : '重新加载'}
                    </Button>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

export default MediaFailuresPanel
