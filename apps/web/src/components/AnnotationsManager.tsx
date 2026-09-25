/** AnnotationsManager — F051 批注管理器 + F052 汇编导出 + F058 复习队列
 *  + N073 颜色语义 + N074 问题清单 + N075 引用格式 + N076/N077 复习项。
 *
 * BookmarksPage「批注」页签：跨篇检索（关键词，服务端 LIKE）、按来源
 * /颜色标签过滤、分页「加载更多」；点击打开原文（reader?entry= 路由
 * 参数由 Reader 消费并定位锚点）；锚点失效（anchor.stale）诚实标注
 * 「原文已变化」，仍可删除。复习页签支持批注与知识卡片两类复习项
 * （kind 徽章、来源 deep link、来源不可用诚实降级）；问题页签管理
 * 阅读问题清单（完成 / 重新打开 / 按链接过滤）。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type CSSProperties } from 'react'
import { BookOpen, Check, Download, Eye, EyeOff, RotateCcw, Trash2 } from 'lucide-react'
import {
  completeReviewQueueItem,
  deleteAnnotation,
  deleteReadingQuestion,
  exportAnnotations,
  getColorLabels,
  listAnnotations,
  listReadingQuestions,
  listReviewQueue,
  patchReadingQuestion,
  postponeReviewQueueItem,
  viewReviewQueueItem,
} from '../api/client'
import type { Annotation, ReadingQuestion, ReviewQueueItem } from '../api/client'
import { dateTimeFormatter } from '../lib/date-format'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

type ManagerTab = 'all' | 'review' | 'questions'

export function AnnotationsManager() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<ManagerTab>('all')
  const [keyword, setKeyword] = useState('')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  // N073：颜色标签过滤（服务端 color= 参数；值 = 调色板原始色名）。
  const [colorFilter, setColorFilter] = useState<string>('all')
  const [citeBibliography, setCiteBibliography] = useState(false)
  const [cursor, setCursor] = useState<string | null>(null)
  const [pages, setPages] = useState<Annotation[][]>([])
  const [exportInfo, setExportInfo] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['annotations-manager', keyword, colorFilter],
    queryFn: () =>
      listAnnotations({
        ...(keyword.trim() === '' ? {} : { q: keyword.trim() }),
        ...(colorFilter === 'all' ? {} : { color: colorFilter }),
      }),
    enabled: tab === 'all',
  })
  const reviewQuery = useQuery({
    queryKey: ['review-queue-manager'],
    queryFn: () => listReviewQueue('due'),
    enabled: tab === 'review',
  })
  const questionsQuery = useQuery({
    queryKey: ['reading-questions-manager'],
    queryFn: () => listReadingQuestions({}),
    enabled: tab === 'questions',
  })
  const colorLabelsQuery = useQuery({
    queryKey: ['annotation-color-labels'],
    queryFn: getColorLabels,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAnnotation(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['annotations-manager'] })
    },
  })
  const completeMutation = useMutation({
    mutationFn: (id: string) => completeReviewQueueItem(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['review-queue-manager'] })
    },
  })
  const postponeMutation = useMutation({
    mutationFn: ({ id, days }: { id: string; days: number }) =>
      postponeReviewQueueItem(id, new Date(Date.now() + days * 86_400_000).toISOString()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['review-queue-manager'] })
    },
  })
  const viewMutation = useMutation({
    mutationFn: (id: string) => viewReviewQueueItem(id),
  })

  const allItems = pages.length > 0 ? pages.flat() : (listQuery.data?.items ?? [])
  const sources = [...new Set(allItems.map((item) => entryHost(item.entryRef)))]
  const items =
    sourceFilter === 'all' ? allItems : allItems.filter((item) => entryHost(item.entryRef) === sourceFilter)

  const exportMutation = useMutation({
    mutationFn: () =>
      exportAnnotations(
        {
          ...(keyword.trim() === '' ? {} : { q: keyword.trim() }),
          citeBibliography,
        },
      ),
    onSuccess: async (blob) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'lumi-annotations.md'
      anchor.click()
      URL.revokeObjectURL(url)
      setExportInfo(`已导出（预计 ${items.length} 条 · ${new Set(items.map((i) => i.entryRef)).size} 篇）`)
    },
    onError: (error) =>
      setExportInfo(error instanceof Error ? `导出失败：${error.message}` : '导出失败'),
  })

  return (
    <div className="flex flex-col gap-3 py-1">
      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="批注视图">
        {(
          [
            { key: 'all', label: '全部批注' },
            { key: 'review', label: '复习' },
            { key: 'questions', label: '问题' },
          ] as const
        ).map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            onClick={() => setTab(entry.key)}
            className={cx(
              'rounded-[var(--lumi-radius-md)] px-3 py-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              tab === entry.key
                ? 'bg-[var(--lumi-accent)] text-[var(--lumi-accent-contrast)]'
                : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            {entry.label}
          </button>
        ))}
        <span className="flex-1" />
        {tab === 'all' && (
          <>
            {/* N075：引用格式行（标题 — 来源, 日期；缺失项「不详」） */}
            <label className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
              <input
                type="checkbox"
                checked={citeBibliography}
                onChange={(e) => setCiteBibliography(e.target.checked)}
                aria-label="导出附带引用格式"
                className="size-3.5"
              />
              引用格式
            </label>
            <Button
              size="sm"
              variant="secondary"
              disabled={exportMutation.isPending || items.length === 0}
              onClick={() => exportMutation.mutate()}
            >
              <Download aria-hidden className="size-3.5" />
              导出汇编（{items.length} 条）
            </Button>
          </>
        )}
      </div>
      {exportInfo !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{exportInfo}</p>
      )}

      {tab === 'all' && (
        <>
          <input
            type="search"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setPages([])
              setCursor(null)
            }}
            placeholder="搜索摘录与批注（服务端检索）"
            aria-label="搜索批注"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)]"
          />
          <div className="flex flex-wrap items-center gap-3">
            {sources.length > 1 && (
              <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                按来源
                <select
                  aria-label="按来源筛选"
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
                >
                  <option value="all">全部</option>
                  {sources.map((source) => (
                    <option key={source} value={source}>{source}</option>
                  ))}
                </select>
              </label>
            )}
            {/* N073：按颜色语义过滤（未命名颜色诚实显示原始色名） */}
            {(colorLabelsQuery.data?.items ?? []).length > 0 && (
              <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                按颜色
                <select
                  aria-label="按颜色筛选"
                  value={colorFilter}
                  onChange={(e) => {
                    setColorFilter(e.target.value)
                    setPages([])
                    setCursor(null)
                  }}
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
                >
                  <option value="all">全部</option>
                  {(colorLabelsQuery.data?.items ?? []).map((label) => (
                    <option key={label.color} value={label.color}>
                      {label.label !== '' ? label.label : label.color}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {listQuery.isPending && <Skeleton className="h-16 w-full" />}
          {listQuery.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              批注加载失败：{listQuery.error instanceof Error ? listQuery.error.message : '请重试'}
            </p>
          )}
          {listQuery.isSuccess && items.length === 0 && (
            <EmptyState
              title="还没有批注"
              description="阅读时选中正文即可添加高亮与批注；批注跨设备同步。"
            />
          )}
          <ul className="flex flex-col gap-2">
            {items.map((item) => (
              <li key={item.id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
                <div className="flex items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
                  <span className="truncate">{entryHost(item.entryRef)}</span>
                  <span>·</span>
                  <span>{dateTimeFormatter.format(Date.parse(item.updatedAt))}</span>
                  <span aria-hidden className="size-2 shrink-0 rounded-full" style={colorDotStyle(item.color)} />
                  {item.anchor.stale === true && (
                    <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                      原文已变化
                    </span>
                  )}
                  <span className="flex-1" />
                  <a
                    href={`/reader?entry=${encodeURIComponent(item.entryRef)}&para=${encodeURIComponent(
                      String(item.anchor.paraId ?? ''),
                    )}`}
                    className="flex items-center gap-1 text-[var(--lumi-accent)] hover:underline"
                    aria-label="打开原文并定位"
                  >
                    <Eye aria-hidden className="size-3.5" /> 定位
                  </a>
                  <button
                    type="button"
                    aria-label="删除批注"
                    onClick={() => deleteMutation.mutate(item.id)}
                    className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
                  >
                    <Trash2 aria-hidden className="size-3.5" />
                  </button>
                </div>
                {item.excerpt !== '' && (
                  <blockquote className="mt-1.5 border-l-2 border-[var(--lumi-separator)] pl-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                    {item.excerpt}
                  </blockquote>
                )}
                {item.note !== '' && (
                  <p className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">{item.note}</p>
                )}
              </li>
            ))}
          </ul>
          {listQuery.data?.nextCursor !== null && pages.length === 0 && listQuery.data?.items.length !== 0 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                const next = listQuery.data?.nextCursor
                if (next !== null && next !== undefined) {
                  setCursor(next)
                  void listAnnotations({
                    q: keyword.trim() === '' ? undefined : keyword.trim(),
                    color: colorFilter === 'all' ? undefined : colorFilter,
                    cursor: next,
                  }).then((page) => setPages([page.items]))
                }
              }}
              disabled={cursor === null && pages.length > 0}
            >
              加载更多
            </Button>
          )}
        </>
      )}

      {tab === 'review' && (
        <ReviewQueueList
          query={reviewQuery}
          onComplete={(id) => completeMutation.mutate(id)}
          onPostpone={(id, days) => postponeMutation.mutate({ id, days })}
          onReveal={(id) => viewMutation.mutate(id)}
        />
      )}

      {tab === 'questions' && <QuestionsPanel query={questionsQuery} />}
    </div>
  )
}

/** N073：批注色点（内容标注语义色，非主题 token；未知色 → 无色点）。 */
function colorDotStyle(color: string): CSSProperties | undefined {
  const dot: Record<string, string> = {
    yellow: '#eab308',
    green: '#65a30d',
    blue: '#2563eb',
    red: '#dc2626',
    purple: '#9333ea',
  }
  const value = dot[color]
  return value === undefined ? undefined : { backgroundColor: value }
}

/** N076/N077：到期复习项（批注 + 知识卡片；来源追踪）。 */
function ReviewQueueList({
  query,
  onComplete,
  onPostpone,
  onReveal,
}: {
  query: { data?: { items: ReviewQueueItem[] } | undefined; isPending: boolean; isError: boolean; error: unknown }
  onComplete: (id: string) => void
  onPostpone: (id: string, days: number) => void
  onReveal: (id: string) => void
}) {
  const [revealed, setRevealed] = useState<string[]>([])
  if (query.isPending) return <Skeleton className="h-16 w-full" />
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        复习队列加载失败：{query.error instanceof Error ? query.error.message : '请重试'}
      </p>
    )
  }
  const items = query.data?.items ?? []
  if (items.length === 0) {
    return (
      <EmptyState
        title="没有到期的复习"
        description="在阅读页对批注点「加入复习」，或在知识卡片上点「加入复习」后，到期的内容会先只显示提示，回忆后再揭示答案。"
      />
    )
  }
  const reveal = (item: ReviewQueueItem) => {
    onReveal(item.id)
    setRevealed((prev) => (prev.includes(item.id) ? prev : [...prev, item.id]))
  }
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => {
        const isRevealed = revealed.includes(item.id)
        const isCard = item.itemKind === 'knowledge_card'
        const sourceUnavailable = item.sourceAvailable === false
        const prompt =
          item.excerpt !== null && item.excerpt !== ''
            ? item.excerpt
            : item.concept !== null && item.concept !== ''
              ? item.concept
              : null
        return (
          <li key={item.id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
              <span>到期 {item.dueAt}{item.due === false ? '（未到期）' : ''}</span>
              {/* N076：kind 徽章 */}
              <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                {isCard ? '知识卡片' : '批注'}
              </span>
              {/* N077：来源不可用诚实降级（不缓存内容，无可展示正文） */}
              {sourceUnavailable && (
                <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                  该来源已不可用
                </span>
              )}
              <span className="flex-1" />
              {/* N077：查看原文段落 deep link（来源失效 → 不提供） */}
              {item.entryRef !== null && !sourceUnavailable && (
                <a
                  href={`/reader?entry=${encodeURIComponent(item.entryRef)}${item.paraId ? `&para=${encodeURIComponent(item.paraId)}` : ''}`}
                  className="flex items-center gap-1 text-[var(--lumi-accent)] hover:underline"
                  aria-label="查看原文段落"
                >
                  <BookOpen aria-hidden className="size-3.5" /> 查看原文段落
                </a>
              )}
            </div>
            {!sourceUnavailable && prompt !== null && (
              <blockquote className="mt-1.5 border-l-2 border-[var(--lumi-separator)] pl-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                {prompt}
              </blockquote>
            )}
            {isRevealed ? (
              <p className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
                {isCard
                  ? item.explanation !== null && item.explanation !== '' ? item.explanation : '（无解释）'
                  : item.note !== null && item.note !== '' ? item.note : '（无批注）'}
              </p>
            ) : (
              !sourceUnavailable && (
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-1.5"
                  onClick={() => reveal(item)}
                >
                  <Eye aria-hidden className="size-3.5" /> {isCard ? '显示解释' : '显示批注'}
                </Button>
              )
            )}
            <div className="mt-2 flex items-center gap-2">
              <Button size="sm" variant="primary" onClick={() => onComplete(item.id)}>
                <RotateCcw aria-hidden className="size-3.5" /> 完成
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onPostpone(item.id, 1)}>明天</Button>
              <Button size="sm" variant="ghost" onClick={() => onPostpone(item.id, 3)}>3 天</Button>
              <Button size="sm" variant="ghost" onClick={() => onPostpone(item.id, 7)}>7 天</Button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** N074：阅读问题清单（完成 / 重新打开 / 按链接过滤）。 */
function QuestionsPanel({
  query,
}: {
  query: { data?: { items: ReadingQuestion[] } | undefined; isPending: boolean; isError: boolean; error: unknown }
}) {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<'all' | 'open' | 'done'>('all')
  const [linkFilter, setLinkFilter] = useState<'all' | 'linked' | 'unlinked'>('all')

  const patchMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'open' | 'done' }) =>
      patchReadingQuestion(id, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['reading-questions-manager'] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteReadingQuestion(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['reading-questions-manager'] })
    },
  })

  if (query.isPending) return <Skeleton className="h-16 w-full" />
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        问题清单加载失败：{query.error instanceof Error ? query.error.message : '请重试'}
      </p>
    )
  }
  const all = query.data?.items ?? []
  const items = all.filter((q) => {
    if (statusFilter !== 'all' && q.status !== statusFilter) return false
    if (linkFilter === 'linked' && q.entryRef === null) return false
    if (linkFilter === 'unlinked' && q.entryRef !== null) return false
    return true
  })
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--lumi-text-secondary)]">
        <label className="flex items-center gap-2">
          状态
          <select
            aria-label="按状态筛选问题"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | 'open' | 'done')}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          >
            <option value="all">全部</option>
            <option value="open">待解决</option>
            <option value="done">已完成</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          链接
          <select
            aria-label="按链接筛选问题"
            value={linkFilter}
            onChange={(e) => setLinkFilter(e.target.value as 'all' | 'linked' | 'unlinked')}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          >
            <option value="all">全部</option>
            <option value="linked">有原文链接</option>
            <option value="unlinked">无链接</option>
          </select>
        </label>
      </div>
      {items.length === 0 && (
        <EmptyState
          title="没有问题"
          description="阅读时在批注弹层点「记为问题」，问题会集中在这里逐个解决。"
        />
      )}
      <ul className="flex flex-col gap-2">
        {items.map((question) => (
          <li key={question.id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
              <span>{dateTimeFormatter.format(Date.parse(question.createdAt))}</span>
              <span
                className={cx(
                  'rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px]',
                  question.status === 'done'
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]'
                    : 'bg-[var(--lumi-accent)] text-[var(--lumi-accent-contrast)]',
                )}
              >
                {question.status === 'done' ? '已完成' : '待解决'}
              </span>
              <span className="flex-1" />
              {question.entryRef !== null && (
                <a
                  href={`/reader?entry=${encodeURIComponent(question.entryRef)}`}
                  className="flex items-center gap-1 text-[var(--lumi-accent)] hover:underline"
                  aria-label="打开原文"
                >
                  <BookOpen aria-hidden className="size-3.5" /> 原文
                </a>
              )}
            </div>
            <p className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">{question.question}</p>
            <div className="mt-2 flex items-center gap-2">
              {question.status === 'open' ? (
                <Button
                  size="sm"
                  variant="primary"
                  disabled={patchMutation.isPending}
                  onClick={() => patchMutation.mutate({ id: question.id, status: 'done' })}
                >
                  <Check aria-hidden className="size-3.5" /> 完成
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={patchMutation.isPending}
                  onClick={() => patchMutation.mutate({ id: question.id, status: 'open' })}
                >
                  <EyeOff aria-hidden className="size-3.5" /> 重新打开
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                className="text-[var(--lumi-danger, #dc2626)]"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(question.id)}
              >
                <Trash2 aria-hidden className="size-3.5" /> 删除
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** entryRef 是 opaque 的：这里只作展示分组用途，不解释内容。 */
function entryHost(entryRef: string): string {
  return entryRef.slice(0, 18)
}
