/** ClipsPage — 网页剪藏页（phase2 Gate 3 Library 域）。
 *
 * 流程：粘贴链接 → BFF SSRF 受限抓取（fetchClipHtml）→ 本地懒提取
 * （extractArticle：defuddle/readability 动态加载 + DOMPurify 清洗）
 * → 自动 createClip。
 * - 抓取错误（clip_fetch_forbidden / clip_fetch_failed 等）：原样展示
 *   BFF message（诚实语义）；
 * - 提取失败：给出「重试 / 只保存链接」两条路（链接模式以 url 为
 *   标题、正文只有链接本身）；
 * - PWA Share Target：App 落地 ?share=1&url=… 后经 sessionStorage
 *   'lumirss-share-url' 一次性交接，本页挂载即读取并清除；
 * - 列表：cursor 分页「加载更多」+ 行内立即删除（与书签同一诚实
 *   语义，无二次确认）；标题点击打开 Dialog 阅读视图——contentHtml
 *   在提取时与渲染前双重 DOMPurify 清洗（sanitizeArticleHtml）。
 */

import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, Globe, Loader2, Trash2 } from 'lucide-react'
import {
  useClipDetail,
  useClips,
  useClipFetchMutation,
  useCreateClipMutation,
  useDeleteClipMutation,
} from '../../api/queries'
import type { Clip } from '../../api/types'
import { formatTimestamp } from '../../lib/date-format'
import { extractArticle } from '../../lib/clip-extract'
import { safeExternalHttpUrl } from '../../lib/safe-external-http-url'
import { sanitizeArticleHtml } from '../../lib/sanitize-article-html'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** PWA Share Target 交接 key（App.handleShareTarget 写入，读取即清除）。 */
const SHARE_URL_KEY = 'lumirss-share-url'

/** 提取失败的固定文案（clip-extract 两个提取器都失败时页面映射到此）。 */
const EXTRACT_FAILED_MESSAGE = '正文提取失败：可重试或只保存链接。'

/** 保存流程的阶段（诚实区分 抓取/提取/保存 三步）。 */
type ClipPhase =
  | { kind: 'idle' }
  | { kind: 'fetching'; url: string }
  | { kind: 'extracting'; url: string }
  | { kind: 'saving'; url: string }
  | { kind: 'saved'; title: string }
  | { kind: 'failed'; url: string; stage: 'fetch' | 'extract' | 'create'; message: string }

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
  'placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

/** 剪藏行：标题按钮（打开阅读 Dialog）+ 安全外链（绝对 http/https 才
 * 渲染）+ url / byline / 时间 + 行内立即删除。 */
function ClipRow({ clip, onOpen }: { clip: Clip; onOpen: (clipRef: string) => void }) {
  const del = useDeleteClipMutation()
  const safeUrl = safeExternalHttpUrl(clip.url)

  return (
    <li>
      <article
        data-clip-ref={clip.ref}
        className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <button
              type="button"
              onClick={() => onOpen(clip.ref)}
              className="text-left text-sm font-medium text-[var(--lumi-text-primary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              {clip.title}
            </button>
            <p className="mt-0.5 flex min-w-0 items-center gap-1 text-xs text-[var(--lumi-text-tertiary)]">
              {safeUrl !== null ? (
                <a
                  href={safeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-w-0 items-center gap-0.5 truncate underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <ExternalLink aria-hidden className="size-3 shrink-0" />
                  <span className="truncate">{clip.url}</span>
                </a>
              ) : (
                <span className="truncate">{clip.url}</span>
              )}
            </p>
            {clip.byline != null && clip.byline !== '' && (
              <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-secondary)]">
                {clip.byline}
              </p>
            )}
            <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              {formatTimestamp(clip.createdAt) || '—'}
            </p>
            {del.isError && (
              <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
                删除失败：{del.error instanceof Error ? del.error.message : '请稍后重试。'}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton
              icon={
                del.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Trash2 aria-hidden className="size-4" />
                )
              }
              label="删除剪藏"
              size="sm"
              touch
              disabled={del.isPending}
              onClick={() => del.mutate(clip.ref)}
            />
          </div>
        </div>
      </article>
    </li>
  )
}

/** 剪藏阅读 Dialog：服务端 Detail 的 contentHtml 再次过 DOMPurify 后
 * 注入（提取时已清洗一次，渲染前是第二道边界）；无正文时回退纯文本。 */
function ClipReadDialog({ clipRef, onClose }: { clipRef: string; onClose: () => void }) {
  const detail = useClipDetail(clipRef)

  return (
    <Dialog
      open
      onClose={onClose}
      title={detail.data?.title ?? '剪藏'}
      panelClassName="max-w-2xl"
      footer={
        <Button variant="ghost" size="sm" onClick={onClose}>
          关闭
        </Button>
      }
    >
      {detail.isPending ? (
        <div className="flex flex-col gap-2" aria-label="剪藏内容加载中">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : detail.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          剪藏内容加载失败：
          {detail.error instanceof Error ? detail.error.message : '请稍后重试。'}
        </p>
      ) : detail.data !== undefined && detail.data.contentHtml.trim() !== '' ? (
        <div className="max-h-[70vh] overflow-y-auto">
          <article
            className={cx(
              'text-sm leading-relaxed text-[var(--lumi-text-primary)]',
              '[&_a]:text-[var(--lumi-accent-text)] [&_a]:underline [&_a]:underline-offset-2',
              '[&_blockquote]:border-l-2 [&_blockquote]:border-[var(--lumi-border)] [&_blockquote]:pl-3',
              '[&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold',
              '[&_h3]:mt-3 [&_h3]:font-semibold [&_h4]:mt-3 [&_h4]:font-semibold',
              '[&_img]:max-w-full [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-6',
              '[&_p]:my-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-[var(--lumi-radius-md)]',
              '[&_pre]:bg-[var(--lumi-surface-selected)] [&_pre]:p-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-6',
            )}
            dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(detail.data.contentHtml) }}
          />
        </div>
      ) : detail.data !== undefined ? (
        <p className="max-h-[70vh] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          {detail.data.contentText}
        </p>
      ) : null}
    </Dialog>
  )
}

export default function ClipsPage() {
  // PWA Share Target 交接：挂载即读一次性 shared url 预填（读取本身是
  // 幂等的纯读；清除放 effect，避免 setState-in-effect 级联渲染）。
  const [input, setInput] = useState(() => {
    try {
      return sessionStorage.getItem(SHARE_URL_KEY) ?? ''
    } catch {
      // sessionStorage 不可用（隐私模式等）绝不影响页面
      return ''
    }
  })
  const [phase, setPhase] = useState<ClipPhase>({ kind: 'idle' })
  const [readingRef, setReadingRef] = useState<string | null>(null)

  const list = useClips()
  const clipFetch = useClipFetchMutation()
  const createClipMutation = useCreateClipMutation()
  const {
    data,
    isPending,
    isError,
    error,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = list

  const clips = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data])

  const busy =
    phase.kind === 'fetching' || phase.kind === 'extracting' || phase.kind === 'saving'

  // 一次性交接完成：立即清除 sessionStorage key（下次挂载不重复预填）。
  useEffect(() => {
    try {
      sessionStorage.removeItem(SHARE_URL_KEY)
    } catch {
      // sessionStorage 不可用绝不影响页面
    }
  }, [])

  const runSave = async (rawUrl: string) => {
    const url = rawUrl.trim()
    if (url === '' || busy) {
      return
    }
    let stage: 'fetch' | 'extract' | 'create' = 'fetch'
    try {
      setPhase({ kind: 'fetching', url })
      const fetched = await clipFetch.mutateAsync(url)
      stage = 'extract'
      setPhase({ kind: 'extracting', url })
      const extracted = await extractArticle(fetched.html, fetched.finalUrl)
      stage = 'create'
      setPhase({ kind: 'saving', url })
      const detail = await createClipMutation.mutateAsync({
        url: fetched.url,
        title: extracted.title,
        byline: extracted.byline,
        contentHtml: extracted.contentHtml,
        contentText: extracted.contentText,
        fetchedAt: new Date().toISOString(),
      })
      setPhase({ kind: 'saved', title: detail.title })
      setInput('')
    } catch (saveError) {
      if (stage === 'extract') {
        // 两个提取器都失败 → 固定文案 + 重试 / 只保存链接
        setPhase({ kind: 'failed', url, stage: 'extract', message: EXTRACT_FAILED_MESSAGE })
      } else {
        setPhase({
          kind: 'failed',
          url,
          stage,
          message:
            saveError instanceof Error ? saveError.message : '保存失败，请稍后重试。',
        })
      }
    }
  }

  // 提取失败的降级保存：标题 = url，正文 = 只有链接本身
  //（contentHtml 在渲染侧仍会再过 DOMPurify）。
  const saveLinkOnly = async () => {
    const url = phase.kind === 'failed' ? phase.url : ''
    if (url === '') {
      return
    }
    try {
      setPhase({ kind: 'saving', url })
      const detail = await createClipMutation.mutateAsync({
        url,
        title: url,
        byline: null,
        contentHtml: `<p>${url}</p>`,
        contentText: url,
        fetchedAt: new Date().toISOString(),
      })
      setPhase({ kind: 'saved', title: detail.title })
      setInput('')
    } catch (saveError) {
      setPhase({
        kind: 'failed',
        url,
        stage: 'create',
        message: saveError instanceof Error ? saveError.message : '保存失败，请稍后重试。',
      })
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 剪藏表单 */}
        <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">网页剪藏</h1>

        <form
          className="mt-2.5 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void runSave(input)
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="sr-only">粘贴链接</span>
            <input
              type="url"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="https://…"
              aria-label="粘贴链接"
              disabled={busy}
              className={inputCls}
            />
          </label>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={busy || input.trim() === ''}
          >
            {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
            剪藏
          </Button>
        </form>

        {/* 保存流程的诚实状态区 */}
        {phase.kind === 'fetching' && (
          <p role="status" className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
            抓取中…
          </p>
        )}
        {phase.kind === 'extracting' && (
          <p role="status" className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
            提取中…
          </p>
        )}
        {phase.kind === 'saving' && (
          <p role="status" className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
            保存中…
          </p>
        )}
        {phase.kind === 'saved' && (
          <p role="status" className="mt-2 text-sm text-[var(--lumi-text-primary)]">
            已保存「{phase.title}」
          </p>
        )}
        {phase.kind === 'failed' && (
          <div className="mt-2 flex flex-col gap-2">
            <p role="alert" className="text-sm text-[var(--lumi-danger)]">
              {phase.message}
            </p>
            {phase.stage === 'extract' ? (
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void runSave(phase.url)}
                >
                  重试
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void saveLinkOnly()}>
                  只保存链接
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void runSave(phase.url)}
                >
                  重试
                </Button>
              </div>
            )}
          </div>
        )}

        {/* 列表 / 诚实状态 */}
        {isPending ? (
          <ul className="mt-3 flex flex-col gap-2" aria-label="剪藏加载中">
            {Array.from({ length: 4 }, (_, i) => (
              <li key={i}>
                <Skeleton className="h-20 w-full" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="mt-6" role="alert">
            <EmptyState
              icon={<Globe aria-hidden className="size-8" />}
              title="剪藏加载失败"
              description={error instanceof Error ? error.message : '请稍后重试。'}
            />
            <div className="flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          </div>
        ) : clips.length === 0 ? (
          <div className="mt-8">
            <EmptyState
              icon={<Globe aria-hidden className="size-8" />}
              title="还没有剪藏"
              description="粘贴链接保存第一篇"
            />
          </div>
        ) : (
          <>
            <ul className="mt-3 flex flex-col gap-2" aria-label="剪藏列表">
              {clips.map((clip) => (
                <ClipRow key={clip.ref} clip={clip} onOpen={setReadingRef} />
              ))}
            </ul>
            {hasNextPage && (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? '加载中…' : '加载更多'}
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      {/* 阅读视图（单实例；key 保证切换剪藏时状态重置） */}
      {readingRef !== null && (
        <ClipReadDialog
          key={readingRef}
          clipRef={readingRef}
          onClose={() => setReadingRef(null)}
        />
      )}
    </div>
  )
}
