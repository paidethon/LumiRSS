/** SnapshotsPage — 网页快照页（phase2 Gate 3 Library 域，monolith）。
 *
 * 生成快照是长任务（10–90s）：pending 期间按钮与输入诚实禁用并显示
 * 「生成中（10–90 秒）」，完成后由 mutation 的 invalidate 自动出现在
 * 列表。monolith_unavailable（503）/ 配额超限等错误原样透出 BFF
 * message（不做转译）。快照 HTML 由 BFF 以沙箱响应下发
 *（/library/assets/{uuid}/page.html），外链 target=_blank —— 沙箱中
 * 打开、无法执行脚本（title 说明）。
 */

import { useState } from 'react'
import { Archive, Loader2, Trash2 } from 'lucide-react'
import {
  useCreateSnapshotMutation,
  useDeleteSnapshotMutation,
  useSnapshots,
} from '../../api/queries'
import type { SnapshotView } from '../../api/types'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'

/** 字节数 → 人类可读（B / KB / MB，大数值取整、小数值保留 1 位小数）。 */
function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '—'
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  const kb = bytes / 1024
  if (kb < 1024) {
    return `${kb >= 100 ? Math.round(kb) : Math.round(kb * 10) / 10} KB`
  }
  const mb = kb / 1024
  return `${mb >= 100 ? Math.round(mb) : Math.round(mb * 10) / 10} MB`
}

/** 快照行：uuid 短码 + 原文 url + 大小/时间 + 沙箱快照外链 + 删除。 */
function SnapshotRow({ snapshot }: { snapshot: SnapshotView }) {
  const del = useDeleteSnapshotMutation()

  return (
    <li>
      <article
        data-snapshot-uuid={snapshot.uuid}
        className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-xs text-[var(--lumi-text-secondary)]">
              {snapshot.uuid.slice(0, 8)}
            </p>
            <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
              {snapshot.url}
            </p>
            <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              {formatBytes(snapshot.bytes)} · {formatTimestamp(snapshot.createdAt) || '—'}
              {snapshot.deduplicated ? ' · 已去重' : ''}
            </p>
            <a
              href={`/api/v1/library/assets/${encodeURIComponent(snapshot.uuid)}/page.html`}
              target="_blank"
              rel="noopener noreferrer"
              title="快照在沙箱中打开，无法执行脚本"
              className="mt-1 inline-flex min-h-6 items-center text-xs text-[var(--lumi-text-secondary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              打开原文快照
            </a>
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
              label="删除快照"
              size="sm"
              touch
              disabled={del.isPending}
              onClick={() => del.mutate(snapshot.uuid)}
            />
          </div>
        </div>
      </article>
    </li>
  )
}

export default function SnapshotsPage() {
  const [url, setUrl] = useState('')
  const list = useSnapshots()
  const create = useCreateSnapshotMutation()
  const { data, isPending, isError, error, refetch } = list

  const creating = create.isPending
  const createError =
    create.isError && create.error instanceof Error
      ? create.error.message
      : create.isError
        ? '快照生成失败，请稍后重试。'
        : null

  const submit = () => {
    const trimmed = url.trim()
    if (trimmed === '' || creating) {
      return
    }
    create.mutate(trimmed, {
      onSuccess: () => {
        setUrl('')
      },
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 生成表单 */}
        <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">网页快照</h1>

        <form
          className="mt-2.5 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <label className="min-w-0 flex-1">
            <span className="sr-only">快照地址</span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              aria-label="快照地址"
              disabled={creating}
              className="w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)] disabled:opacity-50"
            />
          </label>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={creating || url.trim() === ''}
          >
            {creating && <Loader2 aria-hidden className="size-4 animate-spin" />}
            {creating ? '生成中（10–90 秒）' : '生成快照'}
          </Button>
        </form>

        {/* 长任务诚实状态 + 错误（monolith_unavailable 等原样透出 message） */}
        {creating && (
          <p role="status" className="mt-2 text-sm text-[var(--lumi-text-secondary)]">
            快照生成中（10–90 秒），完成后自动出现在下方列表。
          </p>
        )}
        {createError !== null && (
          <p role="alert" className="mt-2 text-sm text-[var(--lumi-danger)]">
            {createError}
          </p>
        )}

        {/* 用量配额行 */}
        {data !== undefined && (
          <p role="status" className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
            已用 {formatBytes(data.usage.bytes)} / 配额 {formatBytes(data.usage.quotaBytes)}
          </p>
        )}

        {/* 列表 / 诚实状态 */}
        {isPending ? (
          <ul className="mt-3 flex flex-col gap-2" aria-label="快照加载中">
            {Array.from({ length: 3 }, (_, i) => (
              <li key={i}>
                <Skeleton className="h-20 w-full" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="mt-6" role="alert">
            <EmptyState
              icon={<Archive aria-hidden className="size-8" />}
              title="快照加载失败"
              description={error instanceof Error ? error.message : '请稍后重试。'}
            />
            <div className="flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          </div>
        ) : data === undefined || data.items.length === 0 ? (
          <div className="mt-8">
            <EmptyState
              icon={<Archive aria-hidden className="size-8" />}
              title="还没有快照"
              description="粘贴链接生成第一份离线快照"
            />
          </div>
        ) : (
          <ul className="mt-3 flex flex-col gap-2" aria-label="快照列表">
            {data.items.map((snapshot) => (
              <SnapshotRow key={snapshot.uuid} snapshot={snapshot} />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
