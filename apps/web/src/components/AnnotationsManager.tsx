/** AnnotationsManager — F051 批注管理器 + F052 汇编导出 + F058 复习队列。
 *
 * BookmarksPage「批注」页签：跨篇检索（关键词，服务端 LIKE）、按来源
 * 过滤（客户端）、分页「加载更多」；点击打开原文（reader?entry= 路由
 * 参数由 Reader 消费并定位锚点）；锚点失效（anchor.stale）诚实标注
 * 「原文已变化」，仍可删除。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Download, Eye, RotateCcw, Trash2 } from 'lucide-react'
import {
  deleteAnnotation,
  exportAnnotations,
  listAnnotations,
  listReviewQueue,
  completeReviewQueueItem,
  postponeReviewQueueItem,
} from '../api/client'
import type { Annotation } from '../api/client'
import { dateTimeFormatter } from '../lib/date-format'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

type ManagerTab = 'all' | 'review'

export function AnnotationsManager() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<ManagerTab>('all')
  const [keyword, setKeyword] = useState('')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [cursor, setCursor] = useState<string | null>(null)
  const [pages, setPages] = useState<Annotation[][]>([])
  const [exportInfo, setExportInfo] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['annotations-manager', keyword],
    queryFn: () => listAnnotations(keyword.trim() === '' ? {} : { q: keyword.trim() }),
  })
  const reviewQuery = useQuery({
    queryKey: ['review-queue-manager'],
    queryFn: () => listReviewQueue('due'),
    enabled: tab === 'review',
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

  const allItems = pages.length > 0 ? pages.flat() : (listQuery.data?.items ?? [])
  const sources = [...new Set(allItems.map((item) => entryHost(item.entryRef)))]
  const items =
    sourceFilter === 'all' ? allItems : allItems.filter((item) => entryHost(item.entryRef) === sourceFilter)

  const exportMutation = useMutation({
    mutationFn: () =>
      exportAnnotations(
        keyword.trim() === ''
          ? {}
          : { q: keyword.trim() },
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
          <Button
            size="sm"
            variant="secondary"
            disabled={exportMutation.isPending || items.length === 0}
            onClick={() => exportMutation.mutate()}
          >
            <Download aria-hidden className="size-3.5" />
            导出汇编（{items.length} 条）
          </Button>
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
                  void listAnnotations({ q: keyword.trim() === '' ? undefined : keyword.trim(), cursor: next }).then(
                    (page) => setPages([page.items]),
                  )
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
        />
      )}
    </div>
  )
}

/** 到期复习项（列表形状与 ReviewQueueItem 对齐） */
interface ReviewItem {
  id: string
  annotationId: string
  entryRef: string
  dueAt: string
  due: boolean | null
  excerpt: string
  note: string
}

function ReviewQueueList({
  query,
  onComplete,
  onPostpone,
}: {
  query: { data?: { items: ReviewItem[] } | undefined; isPending: boolean; isError: boolean; error: unknown }
  onComplete: (id: string) => void
  onPostpone: (id: string, days: number) => void
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
        description="在阅读页对批注点「加入复习」后，到期的批注会先只显示摘录，回忆后再揭示答案。"
      />
    )
  }
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => {
        const isRevealed = revealed.includes(item.id)
        return (
          <li key={item.id} className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              到期 {item.dueAt}{item.due === false ? '（未到期）' : ''}
            </p>
            {item.excerpt !== '' && (
              <blockquote className="mt-1.5 border-l-2 border-[var(--lumi-separator)] pl-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                {item.excerpt}
              </blockquote>
            )}
            {isRevealed ? (
              <p className="mt-1.5 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
                {item.note !== '' ? item.note : '（无批注）'}
              </p>
            ) : (
              <Button size="sm" variant="secondary" className="mt-1.5" onClick={() => setRevealed((prev) => [...prev, item.id])}>
                <Eye aria-hidden className="size-3.5" /> 显示批注
              </Button>
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

/** entryRef 是 opaque 的：这里只作展示分组用途，不解释内容。 */
function entryHost(entryRef: string): string {
  return entryRef.slice(0, 18)
}
