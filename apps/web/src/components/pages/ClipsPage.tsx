/** ClipsPage — 网页剪藏页（phase2 Gate 3 Library 域；P0-03 后为服务端
 * 可信管线）。
 *
 * 流程：粘贴链接 → POST /library/clips/fetch（服务端 SSRF 钉住拨号 +
 * 提取 + allow-list 清洗，返回 title/byline/contentHtml/contentText/
 * finalUrl）→ 页面展示服务端文章供确认 → 保存只提交 {url, finalUrl}
 * （客户端派生的 title/HTML 不再提交——服务端按 finalUrl 重取重导出，
 * 浏览器提交的任何正文都不被信任）。
 * - 抓取错误（clip_fetch_forbidden / clip_fetch_failed 等）：原样展示
 *   BFF message（诚实语义）+ 重试；
 * - 确认面板正文渲染：contentHtml 已是服务端清洗产物，渲染前仍过
 *   DOMPurify（sanitizeArticleHtml——全站唯一渲染终界，不变）；
 * - PWA Share Target：App 落地 ?share=1&url=… 后经 sessionStorage
 *   'lumirss-share-url' 一次性交接，本页挂载即读取并清除；
 * - 列表：cursor 分页「加载更多」+ 行内立即删除（与书签同一诚实
 *   语义，无二次确认）；标题点击打开 Dialog 阅读视图（同样渲染前
 *   sanitize）。
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ExternalLink, Globe, Loader2, Lock, LockOpen, RefreshCw, Trash2, X } from 'lucide-react'
import {
  useApplyClipCandidateMutation,
  useClipCandidate,
  useClipLockMutation,
  useClips,
  useClipFetchMutation,
  useCreateClipMutation,
  useDeleteClipMutation,
  useDiscardClipCandidateMutation,
  useClipRefreshMutation,
} from '../../api/queries'
import { getClipFull, saveClipRevision } from '../../api/client'
import type { Clip, ClipFetchArticleResult } from '../../api/types'
import { formatTimestamp } from '../../lib/date-format'
import { LibraryTrashPanel } from '../LibraryTrashPanel'
import { safeExternalHttpUrl } from '../../lib/safe-external-http-url'
import { sanitizeArticleHtml } from '../../lib/sanitize-article-html'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { ClipRevisionBadge, ClipRevisionDialog, safeOriginalHtml } from '../ClipRevisionDialog'
import { ClipCleanupPreviewDialog } from '../ClipCleanupPreviewDialog'
import { BulkPasteDialog } from '../BulkPasteDialog'
import { BatchEditDialog } from '../BatchEditDialog'
import { CheckLinksDialog } from '../CheckLinksDialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** PWA Share Target 交接 key（App.handleShareTarget 写入，读取即清除）。 */
const SHARE_URL_KEY = 'lumirss-share-url'

/** 保存流程的阶段（诚实区分 抓取 / 确认 / 保存 三步；提取与清洗已
 * 全部在服务端完成，客户端不再有「提取」阶段）。 */
type ClipPhase =
  | { kind: 'idle' }
  | { kind: 'fetching'; url: string }
  | { kind: 'confirming'; fetched: ClipFetchArticleResult }
  | { kind: 'saving'; url: string }
  | { kind: 'saved'; title: string }
  | { kind: 'failed'; url: string; stage: 'fetch' | 'create'; message: string }

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
  'placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

/** 剪藏行：标题按钮（打开阅读 Dialog）+ 安全外链（绝对 http/https 才
 * 渲染）+ url / byline / 时间 + 多选（F081/F087）+ 行内立即删除。 */
function ClipRow({
  clip,
  onOpen,
  selected,
  onToggleSelect,
}: {
  clip: Clip
  onOpen: (clipRef: string) => void
  selected: boolean
  onToggleSelect: (ref: string) => void
}) {
  const del = useDeleteClipMutation()
  const safeUrl = safeExternalHttpUrl(clip.url)

  return (
    <li>
      <article
        data-clip-ref={clip.ref}
        className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5"
      >
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(clip.ref)}
            aria-label={`选择剪藏：${clip.title}`}
            className="mt-1 size-4 shrink-0 accent-[var(--lumi-accent)]"
          />
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

/** 剪藏阅读 Dialog：/full 详情（content/original/revised/locked/candidate）。
 * 正文渲染前仍过 DOMPurify（sanitizeArticleHtml——全站唯一渲染终界）。
 * N122：锁定 toggle + 刷新（候选/应用语义）+ 候选徽标（查看候选 /
 * 清理预览 / 应用候选 / 丢弃候选）。 */
function ClipReadDialog({ clipRef, onClose }: { clipRef: string; onClose: () => void }) {
  const uuid = clipRef.startsWith('library:')
    ? clipRef.slice('library:'.length)
    : clipRef
  const full = useQuery({
    queryKey: ['library', 'clips', 'full', clipRef],
    queryFn: ({ signal }) => getClipFull(uuid, signal),
  })
  const lock = useClipLockMutation()
  const refresh = useClipRefreshMutation()
  const applyCandidate = useApplyClipCandidateMutation()
  const discardCandidate = useDiscardClipCandidateMutation()
  const queryClient = useQueryClient()
  const [revising, setRevising] = useState(false)
  const [viewingOriginal, setViewingOriginal] = useState(false)
  const [viewingCandidate, setViewingCandidate] = useState(false)
  const [cleaningCandidate, setCleaningCandidate] = useState(false)
  const [candidateKeepIds, setCandidateKeepIds] = useState<string[] | null>(null)

  const detail = full.data
  const locked = detail?.locked === true
  const refreshStatus = refresh.data?.status

  const articleClasses = cx(
    'text-sm leading-relaxed text-[var(--lumi-text-primary)]',
    '[&_a]:text-[var(--lumi-accent-text)] [&_a]:underline [&_a]:underline-offset-2',
    '[&_blockquote]:border-l-2 [&_blockquote]:border-[var(--lumi-border)] [&_blockquote]:pl-3',
    '[&_img]:max-w-full [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-6',
    '[&_p]:my-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-[var(--lumi-radius-md)]',
    '[&_pre]:bg-[var(--lumi-surface-selected)] [&_pre]:p-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-6',
  )

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['library', 'clips'] })
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={detail?.title ?? '剪藏'}
      panelClassName="max-w-2xl"
      footer={
        <div className="flex w-full flex-wrap items-center gap-2">
          {detail?.revised != null && (
            <ClipRevisionBadge
              clipRef={clipRef}
              revised={detail.revised}
              viewingOriginal={viewingOriginal}
              onToggleOriginal={() => setViewingOriginal((v) => !v)}
            />
          )}
          {/* N122：锁定 toggle（唯一覆盖开关） */}
          <Button
            variant={locked ? 'primary' : 'ghost'}
            size="sm"
            data-clip-lock-toggle=""
            aria-pressed={locked}
            disabled={lock.isPending || full.isPending}
            onClick={() =>
              lock.mutate(
                { clipRef: uuid, locked: !locked },
                { onSuccess: () => void invalidate() },
              )
            }
          >
            {locked ? (
              <Lock aria-hidden className="size-3.5" />
            ) : (
              <LockOpen aria-hidden className="size-3.5" />
            )}
            {locked ? '已锁定' : '锁定'}
          </Button>
          {/* N122：刷新（锁定 → 只存候选；未锁定 → 直接应用） */}
          <Button
            variant="ghost"
            size="sm"
            data-clip-refresh=""
            disabled={refresh.isPending || full.isPending}
            onClick={() =>
              refresh.mutate(uuid, { onSuccess: () => void invalidate() })
            }
          >
            <RefreshCw aria-hidden className="size-3.5" />
            {refresh.isPending ? '刷新中…' : '刷新'}
          </Button>
          {detail?.candidate != null && (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-xs text-[var(--lumi-accent-text)]"
              data-clip-candidate-badge=""
            >
              有候选版本
            </span>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => setRevising(true)}>
              修订正文
            </Button>
            <Button variant="ghost" size="sm" onClick={onClose}>
              关闭
            </Button>
          </div>
        </div>
      }
    >
      {/* 刷新 / 候选操作的状态区（诚实逐项展示） */}
      {(refreshStatus !== undefined || lock.isError || refresh.isError || applyCandidate.isError || discardCandidate.isError) && (
        <div className="mb-2 flex flex-col gap-1 text-xs" data-clip-refresh-status="">
          {refreshStatus === 'candidate' && (
            <p role="status" className="text-[var(--lumi-text-secondary)]">
              已锁定：重新抓取的内容只存为候选版本，当前内容未被改动。
            </p>
          )}
          {refreshStatus === 'applied' && (
            <p role="status" className="text-[var(--lumi-text-secondary)]">
              已应用重新抓取的内容（原始版本保留在「查看原始版本」中）。
            </p>
          )}
          {refreshStatus === 'unchanged' && (
            <p role="status" className="text-[var(--lumi-text-secondary)]">
              线上内容与当前版本一致，无需更新。
            </p>
          )}
          {(lock.isError || refresh.isError || applyCandidate.isError || discardCandidate.isError) && (
            <p role="alert" className="text-[var(--lumi-danger)]">
              {(lock.error ?? refresh.error ?? applyCandidate.error ?? discardCandidate.error) instanceof Error
                ? String(
                    (lock.error ?? refresh.error ?? applyCandidate.error ?? discardCandidate.error)?.message,
                  )
                : '操作失败，请稍后重试。'}
            </p>
          )}
        </div>
      )}

      {revising && <ClipRevisionDialog clipRef={clipRef} onClose={() => setRevising(false)} />}
      {cleaningCandidate && detail?.candidate != null && (
        // N123：候选版本的清理预览（确认后带 keepIds 应用候选）。
        <CandidateCleanupFlow
          clipRef={uuid}
          onDone={async (keepIds) => {
            setCleaningCandidate(false)
            setCandidateKeepIds(keepIds)
          }}
        />
      )}

      {viewingCandidate && detail?.candidate != null ? (
        // 候选版本视图：查看候选（净化渲染）+ 清理预览 + 应用/丢弃。
        <div className="flex max-h-[70vh] flex-col gap-2">
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            候选版本（{detail.candidate.fetchedAt} 抓取；应用前不会改动当前内容）
          </p>
          <CandidateHtml clipRef={uuid} articleClasses={articleClasses} />
          <div className="flex flex-wrap items-center gap-2" data-clip-candidate-actions="">
            <Button
              variant="secondary"
              size="sm"
              data-clip-candidate-cleanup=""
              disabled={cleaningCandidate}
              onClick={() => setCleaningCandidate(true)}
            >
              清理预览
            </Button>
            <Button
              variant="primary"
              size="sm"
              data-clip-candidate-apply=""
              disabled={locked || applyCandidate.isPending}
              onClick={() =>
                applyCandidate.mutate(
                  { clipRef: uuid, keepIds: candidateKeepIds ?? undefined },
                  {
                    onSuccess: async () => {
                      setViewingCandidate(false)
                      setCandidateKeepIds(null)
                      await invalidate()
                    },
                  },
                )
              }
            >
              {locked ? '解锁后才能应用' : candidateKeepIds !== null ? '应用清理后的候选' : '应用候选'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              data-clip-candidate-discard=""
              disabled={discardCandidate.isPending}
              onClick={() =>
                discardCandidate.mutate(uuid, {
                  onSuccess: async () => {
                    setViewingCandidate(false)
                    await invalidate()
                  },
                })
              }
            >
              丢弃候选
            </Button>
          </div>
          {locked && (
            <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
              剪藏已锁定：应用候选前需要先解锁。
            </p>
          )}
        </div>
      ) : viewingOriginal && detail?.original != null ? (
        <div className="max-h-[70vh] overflow-y-auto">
          <p className="mb-2 text-xs text-[var(--lumi-text-tertiary)]">原始版本（不可变；不入搜索索引）</p>
          <article
            className={articleClasses}
            dangerouslySetInnerHTML={{ __html: safeOriginalHtml(detail.original) }}
          />
        </div>
      ) : full.isPending ? (
        <div className="flex flex-col gap-2" aria-label="剪藏内容加载中">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : full.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          剪藏内容加载失败：
          {full.error instanceof Error ? full.error.message : '请稍后重试。'}
        </p>
      ) : detail !== undefined && detail.content.html.trim() !== '' ? (
        <div className="max-h-[70vh] overflow-y-auto">
          {detail.candidate != null && (
            <button
              type="button"
              className="mb-2 text-xs text-[var(--lumi-accent-text)] underline underline-offset-2"
              data-clip-candidate-view=""
              onClick={() => setViewingCandidate(true)}
            >
              查看候选版本
            </button>
          )}
          <article
            className={articleClasses}
            dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(detail.content.html) }}
          />
        </div>
      ) : detail !== undefined ? (
        <p className="max-h-[70vh] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          {detail.content.text}
        </p>
      ) : null}
    </Dialog>
  )
}

/** 候选 HTML 的净化渲染（查看候选时使用；渲染终界一致）。 */
function CandidateHtml({
  clipRef,
  articleClasses,
}: {
  clipRef: string
  articleClasses: string
}) {
  const candidate = useClipCandidate(clipRef)
  if (candidate.isPending) return <Skeleton className="h-24 w-full" />
  if (candidate.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        候选内容加载失败。
      </p>
    )
  }
  return (
    <div className="max-h-72 overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
      <article
        className={articleClasses}
        dangerouslySetInnerHTML={{
          __html: sanitizeArticleHtml(candidate.data?.contentHtml ?? ''),
        }}
      />
    </div>
  )
}

/** 候选清理预览流程：抓候选 HTML → 块勾选 → 把 keepIds 交回调用方。 */
function CandidateCleanupFlow({
  clipRef,
  onDone,
}: {
  clipRef: string
  onDone: (keepIds: string[]) => void | Promise<void>
}) {
  const candidate = useClipCandidate(clipRef)
  if (candidate.data === undefined) return null
  return (
    <ClipCleanupPreviewDialog
      html={candidate.data.contentHtml}
      confirmLabel="以清理结果应用"
      onConfirm={(keepIds) => void onDone(keepIds)}
      onCancel={() => void onDone([])}
    />
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
  const [trashOpen, setTrashOpen] = useState(false)
  const [phase, setPhase] = useState<ClipPhase>({ kind: 'idle' })
  const [readingRef, setReadingRef] = useState<string | null>(null)
  // N121：批量粘贴（textarea 逐行 URL → bulk-links）。
  const [bulkPasteOpen, setBulkPasteOpen] = useState(false)
  // N123：清理预览（确认面板中的可选步骤；keepIds 随保存一起生效）。
  const [cleanupOpen, setCleanupOpen] = useState(false)
  // F081/F087：多选批量操作（复用书签页同款对话框）。
  const [selectedRefs, setSelectedRefs] = useState<Set<string>>(new Set())
  const [batchEditOpen, setBatchEditOpen] = useState(false)
  const [checkLinksOpen, setCheckLinksOpen] = useState(false)

  function toggleSelect(ref: string) {
    setSelectedRefs((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

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
    phase.kind === 'fetching' || phase.kind === 'saving'

  // 一次性交接完成：立即清除 sessionStorage key（下次挂载不重复预填）。
  useEffect(() => {
    try {
      sessionStorage.removeItem(SHARE_URL_KEY)
    } catch {
      // sessionStorage 不可用绝不影响页面
    }
  }, [])

  /** 第一步：服务端抓取 + 提取（无任何客户端提取），结果进入确认态。 */
  const runFetch = async (rawUrl: string) => {
    const url = rawUrl.trim()
    if (url === '' || busy) {
      return
    }
    setPhase({ kind: 'fetching', url })
    try {
      const fetched = await clipFetch.mutateAsync(url)
      setPhase({ kind: 'confirming', fetched })
      setInput('')
    } catch (fetchError) {
      setPhase({
        kind: 'failed',
        url,
        stage: 'fetch',
        message:
          fetchError instanceof Error ? fetchError.message : '抓取失败，请稍后重试。',
      })
    }
  }

  /** 第二步：用户确认服务端文章 → 只提交 {url, finalUrl}。标题/正文
      由服务端按 finalUrl 重取重导出，客户端永不提交正文。
      N123：cleanupKeepIds 非空时，保存成功后再走既有 PATCH revision
      （同一净化管线）应用清理结果；修订失败不影响「已保存」事实。 */
  const confirmSave = async (cleanupKeepIds?: string[]) => {
    if (phase.kind !== 'confirming') return
    const { url, finalUrl } = phase.fetched
    setPhase({ kind: 'saving', url })
    try {
      const detail = await createClipMutation.mutateAsync({ url, finalUrl })
      if (cleanupKeepIds && cleanupKeepIds.length > 0) {
        try {
          await saveClipRevision(detail.ref.replace('library:', ''), {
            blocks: cleanupKeepIds,
            note: '清理预览确认',
          })
          setPhase({ kind: 'saved', title: `${detail.title}（已应用清理）` })
          return
        } catch {
          // 清理保存失败：剪藏已存在——诚实标注，可稍后在阅读视图重试。
          setPhase({ kind: 'saved', title: `${detail.title}（清理未应用，可在阅读视图重试）` })
          return
        }
      }
      setPhase({ kind: 'saved', title: detail.title })
    } catch (saveError) {
      setPhase({
        kind: 'failed',
        url,
        stage: 'create',
        message: saveError instanceof Error ? saveError.message : '保存失败，请稍后重试。',
      })
    }
  }

  const cancelConfirm = () => {
    setPhase({ kind: 'idle' })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 回收站开关 + 多选批量操作（F081/F087） + 剪藏表单 */}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">网页剪藏</h1>
          {selectedRefs.size > 0 && (
            <>
              <span data-selection-count="" className="text-xs text-[var(--lumi-text-secondary)]">
                已选 {selectedRefs.size} 条
              </span>
              <Button size="sm" variant="secondary" onClick={() => setBatchEditOpen(true)}>
                批量编辑
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setCheckLinksOpen(true)}>
                检查链接
              </Button>
            </>
          )}
          <button
            type="button"
            aria-pressed={trashOpen}
            onClick={() => setTrashOpen((v) => !v)}
            className="ml-auto min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
          >
            回收站
          </button>
          <Button
            size="sm"
            variant="ghost"
            data-bulk-paste-open=""
            onClick={() => setBulkPasteOpen(true)}
          >
            批量粘贴
          </Button>
        </div>
        {trashOpen && <LibraryTrashPanel />}

        <form
          className="mt-2.5 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void runFetch(input)
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
            正在抓取并提取正文…
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
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setInput(phase.url)
                  void runFetch(phase.url)
                }}
              >
                重试
              </Button>
            </div>
          </div>
        )}
        {phase.kind === 'confirming' && (
          // 确认面板：服务端提取的文章（title/byline/正文）。正文是服务端
          // allow-list 清洗产物，渲染前仍过 DOMPurify（渲染终界不变）。
          <section
            aria-label="确认剪藏内容"
            className="mt-2.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3.5"
          >
            <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
              {phase.fetched.title}
            </h2>
            <p className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 text-xs text-[var(--lumi-text-tertiary)]">
              {phase.fetched.byline != null && phase.fetched.byline !== '' && (
                <span className="truncate">{phase.fetched.byline}</span>
              )}
              <span className="min-w-0 truncate">{phase.fetched.finalUrl}</span>
            </p>
            {phase.fetched.contentHtml.trim() !== '' ? (
              <div className="mt-2 max-h-[40vh] overflow-y-auto">
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
                  dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(phase.fetched.contentHtml) }}
                />
              </div>
            ) : (
              <p className="mt-2 max-h-[40vh] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
                {phase.fetched.contentText}
              </p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={() => void confirmSave()}
                disabled={phase.kind !== 'confirming' || createClipMutation.isPending}
              >
                <Check aria-hidden className="size-4" />
                保存剪藏
              </Button>
              {/* N123：清理预览（可选步骤；确认后按保留块保存） */}
              <Button
                variant="secondary"
                size="sm"
                data-cleanup-preview-open=""
                onClick={() => setCleanupOpen(true)}
                disabled={phase.fetched.contentHtml.trim() === ''}
              >
                清理预览
              </Button>
              <Button variant="ghost" size="sm" onClick={cancelConfirm} disabled={createClipMutation.isPending}>
                <X aria-hidden className="size-4" />
                取消
              </Button>
            </div>
          </section>
        )}
        {cleanupOpen && phase.kind === 'confirming' && (
          <ClipCleanupPreviewDialog
            html={phase.fetched.contentHtml}
            confirmLabel="保存并应用清理"
            onConfirm={(keepIds) => {
              setCleanupOpen(false)
              void confirmSave(keepIds)
            }}
            onCancel={() => setCleanupOpen(false)}
          />
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
                <ClipRow
                  key={clip.ref}
                  clip={clip}
                  onOpen={setReadingRef}
                  selected={selectedRefs.has(clip.ref)}
                  onToggleSelect={toggleSelect}
                />
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

      {/* F081/F087：批量编辑 / 检查链接（与书签页同款对话框；零 FreshRSS/Vault 接触） */}
      {batchEditOpen && selectedRefs.size > 0 && (
        <BatchEditDialog refs={[...selectedRefs]} onClose={() => { setBatchEditOpen(false); setSelectedRefs(new Set()) }} />
      )}
      {checkLinksOpen && selectedRefs.size > 0 && (
        <CheckLinksDialog refs={[...selectedRefs]} onClose={() => { setCheckLinksOpen(false); setSelectedRefs(new Set()) }} />
      )}

      {/* N121：批量粘贴（逐行 URL → bulk-links，逐条结果展示） */}
      {bulkPasteOpen && (
        <BulkPasteDialog target="clip" onClose={() => setBulkPasteOpen(false)} />
      )}

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
