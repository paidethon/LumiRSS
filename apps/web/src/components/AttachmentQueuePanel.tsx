/** AttachmentQueuePanel — N065 附件下载队列（设备本地）。
 *
 * 集成：Reader 在 EnclosurePlayers 之后挂载；列出当前文章的 enclosure：
 * - 白名单类型（音频/视频/图片/PDF/EPUB）给「下载」按钮；
 *   脚本/可执行等白名单外类型诚实标注「不支持下载」，绝不入队；
 * - 队列项显示 名称/大小/进度/状态；取消（在途）、重试一次（失败）；
 * - 完成 → Blob → object URL → anchor 交给浏览器下载（本组件不落盘）；
 * - 磁盘上限 200MB（元数据口径）：放不下时 LRU 逐出旧条目并逐条诚实
 *   提示；单条超限拒绝；重复 URL 忽略。
 * 元数据持久化 localStorage（lib/attachment-queue），二进制从不落
 * localStorage。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, RotateCcw, X } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import {
  attachmentFilenameFromUrl,
  downloadAttachmentToBlob,
  formatAttachmentBytes,
  isAllowedAttachment,
  newAttachmentId,
  planQueueCapacity,
  readAttachmentQueue,
  triggerBrowserDownload,
  writeAttachmentQueue,
  type AttachmentQueueItem,
} from '../lib/attachment-queue'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

const STATUS_LABELS: Record<AttachmentQueueItem['status'], string> = {
  queued: '排队中',
  downloading: '下载中',
  done: '已下载',
  failed: '失败',
  canceled: '已取消',
}

export default function AttachmentQueuePanel({ detail }: { detail: EntryDetail }) {
  const enclosures = detail.enclosure ?? []
  // 挂载时把上次会话遗留的 downloading 归为 failed（下载随页面离开被中止，
  // 元数据可能停留在 downloading——诚实转为可重试的失败，避免假「下载中」）。
  const [items, setItems] = useState<AttachmentQueueItem[]>(() =>
    readAttachmentQueue().map((item) =>
      item.status === 'downloading'
        ? { ...item, status: 'failed' as const, error: '上次下载被中断（离开页面）' }
        : item,
    ),
  )
  const [notice, setNotice] = useState<string | null>(null)
  const abortsRef = useRef<Map<string, AbortController>>(new Map())

  // 元数据持久化（每次状态变化同步写 localStorage）
  useEffect(() => {
    writeAttachmentQueue(items)
  }, [items])

  // 卸载：中止全部在途下载（队列元数据已保留为 failed/canceled 之前的
  // 状态——卸载时把在途项标记为 failed（诚实：下载被打断））。
  useEffect(() => {
    const aborts = abortsRef.current
    return () => {
      for (const controller of aborts.values()) controller.abort()
      aborts.clear()
    }
  }, [])

  const patchItem = useCallback((id: string, patch: Partial<AttachmentQueueItem>) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)))
  }, [])

  const startDownload = useCallback(
    (item: AttachmentQueueItem) => {
      const controller = new AbortController()
      abortsRef.current.set(item.id, controller)
      patchItem(item.id, { status: 'downloading', progress: 0, loaded: 0, error: null })
      void downloadAttachmentToBlob(item.url, {
        signal: controller.signal,
        onProgress: ({ loaded, total }) => {
          patchItem(item.id, {
            loaded,
            progress: total !== null && total > 0 ? Math.min(100, (loaded / total) * 100) : 0,
          })
        },
      })
        .then(({ blob }) => {
          abortsRef.current.delete(item.id)
          triggerBrowserDownload(blob, item.name)
          patchItem(item.id, { status: 'done', progress: 100, loaded: blob.size, size: blob.size })
        })
        .catch((error: unknown) => {
          abortsRef.current.delete(item.id)
          const aborted =
            (error as { name?: string } | null)?.name === 'AbortError' ||
            controller.signal.aborted
          patchItem(
            item.id,
            aborted
              ? { status: 'canceled', error: null }
              : {
                  status: 'failed',
                  error: error instanceof Error ? error.message : '下载失败',
                },
          )
        })
    },
    [patchItem],
  )

  const addToQueue = useCallback(
    (url: string) => {
      setNotice(null)
      const current = readAttachmentQueue()
      // 重复 URL 忽略（已在队列中的附件不再加入）
      if (current.some((item) => item.url === url)) {
        setNotice('该附件已在队列中。')
        return
      }
      // 大小未知 → 按 0 估算；真实大小在完成时回填（诚实口径）
      const plan = planQueueCapacity(current, 0)
      if (plan.evicted.length > 0) {
        setNotice(`已清理 ${plan.evicted.length} 个最旧的下载记录以腾出空间。`)
      }
      const item: AttachmentQueueItem = {
        id: newAttachmentId(),
        url,
        name: attachmentFilenameFromUrl(url),
        size: null,
        status: 'queued',
        progress: 0,
        loaded: 0,
        error: null,
        addedAt: Date.now(),
        retries: 0,
      }
      const next = [...plan.kept, item]
      setItems(next)
      writeAttachmentQueue(next)
      startDownload(item)
    },
    [startDownload],
  )

  const cancel = (item: AttachmentQueueItem) => {
    abortsRef.current.get(item.id)?.abort()
  }

  const retry = (item: AttachmentQueueItem) => {
    if (item.retries >= 1) return // retry-once
    patchItem(item.id, { retries: item.retries + 1 })
    startDownload({ ...item, retries: item.retries + 1 })
  }

  const queueFor = (url: string): AttachmentQueueItem | null =>
    items.find((item) => item.url === url) ?? null

  if (enclosures.length === 0) return null

  const queueActive = items.filter((item) => item.status !== 'done')

  return (
    <div
      data-testid="attachment-queue"
      className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">附件下载</h3>
      <ul className="mt-2 flex flex-col gap-1.5">
        {enclosures.map((enclosure) => {
          const allowed = isAllowedAttachment(enclosure.href, enclosure.type)
          const queued = queueFor(enclosure.href)
          return (
            <li
              key={enclosure.href}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] px-1 py-1 text-xs"
            >
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]" title={enclosure.href}>
                {attachmentFilenameFromUrl(enclosure.href)}
                {enclosure.type ? ` · ${enclosure.type}` : ''}
              </span>
              {!allowed ? (
                <span className="shrink-0 text-[var(--lumi-text-tertiary)]">不支持下载</span>
              ) : queued === null ? (
                <button
                  type="button"
                  data-testid="attachment-add"
                  onClick={() => addToQueue(enclosure.href)}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <Download aria-hidden className="size-3.5" />
                  下载
                </button>
              ) : (
                <AttachmentQueueRowState
                  item={queued}
                  onCancel={() => cancel(queued)}
                  onRetry={() => retry(queued)}
                />
              )}
            </li>
          )
        })}
      </ul>

      {notice !== null && (
        <p role="status" data-testid="attachment-queue-notice" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}

      {queueActive.length > 0 && (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
          队列上限 200MB（本机估算）；下载由浏览器保存到本机，服务器不留存。
        </p>
      )}
    </div>
  )
}

/** 单个队列项的状态区（进度/取消/重试一次）。 */
function AttachmentQueueRowState({
  item,
  onCancel,
  onRetry,
}: {
  item: AttachmentQueueItem
  onCancel: () => void
  onRetry: () => void
}) {
  if (item.status === 'done') {
    return (
      <span className="shrink-0 text-[var(--lumi-accent-text)]">
        {STATUS_LABELS.done} · {formatAttachmentBytes(item.size)}
      </span>
    )
  }
  const inFlight = item.status === 'downloading' || item.status === 'queued'
  return (
    <span
      className={cx(
        'flex shrink-0 items-center gap-1.5',
        item.status === 'failed' && 'text-[var(--lumi-danger)]',
      )}
    >
      <span data-testid="attachment-status" aria-live="polite">
        {STATUS_LABELS[item.status]}
        {inFlight
          ? item.progress > 0
            ? ` ${Math.round(item.progress)}%`
            : ` ${formatAttachmentBytes(item.loaded)}`
          : item.error !== null
            ? `：${item.error}`
            : ''}
      </span>
      {inFlight && (
        <IconButton
          size="sm"
          icon={<X aria-hidden className="size-4" />}
          label={`取消下载 ${item.name}`}
          touch
          onClick={onCancel}
        />
      )}
      {item.status === 'failed' && item.retries < 1 && (
        <IconButton
          size="sm"
          icon={<RotateCcw aria-hidden className="size-4" />}
          label={`重试下载 ${item.name}`}
          touch
          onClick={onRetry}
        />
      )}
    </span>
  )
}
