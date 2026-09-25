/** SnapshotDiagnosticsPanel — F033 资源诊断 + F034 版本（SnapshotsPage 行内展开）。
 *
 * 资源状态列表（ok/failed/skipped/missing 如实）+「重试失败项」（无失败
 * no-op）；版本下拉（时间+hash 前 8）+「对比」视图（unified diff 行标色）。
 * N124：资源预算（真实文件大小 + 内联 data: URI 分类拆分）与按类选择性
 * 清理（只删选中类别；条目本体保留，被清资源随后在清单中标 missing）。
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, GitCompare, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import {
  cleanupSnapshotResources,
  createSnapshotVersion,
  diffSnapshotVersions,
  getSnapshotDetail,
  getSnapshotStorage,
  listSnapshotVersions,
  retryFailedSnapshotResources,
  type SnapshotCleanupKind,
} from '../api/client'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

const RESOURCE_STATUS_TEXT: Record<string, string> = {
  ok: '正常',
  failed: '失败',
  skipped: '内联',
  missing: '缺失',
}

const CLEANUP_KIND_TEXT: Record<SnapshotCleanupKind, string> = {
  images: '图片',
  styles: '样式',
  attachments: '附件',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const CLEANUP_KINDS: SnapshotCleanupKind[] = ['images', 'styles', 'attachments']

export default function SnapshotDiagnosticsPanel({ uuid }: { uuid: string }) {
  const detail = useQuery({
    queryKey: ['snapshot-detail', uuid],
    queryFn: ({ signal }) => getSnapshotDetail(uuid, signal),
  })
  const versions = useQuery({
    queryKey: ['snapshot-versions', uuid],
    queryFn: ({ signal }) => listSnapshotVersions(uuid, signal),
  })
  // N124：资源预算（真实文件大小 + 内联资源分类）。
  const storage = useQuery({
    queryKey: ['snapshot-storage', uuid],
    queryFn: ({ signal }) => getSnapshotStorage(uuid, signal),
  })
  const [retrying, setRetrying] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [cleaningKind, setCleaningKind] = useState<SnapshotCleanupKind | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [compareWith, setCompareWith] = useState<number | null>(null)

  const [selected, setSelected] = useState<number | null>(null)
  const list = versions.data?.versions ?? []
  const active = list.find((v) => v.versionId === selected) ?? list[list.length - 1] ?? null

  async function runRetry() {
    setRetrying(true)
    setNotice(null)
    try {
      const result = await retryFailedSnapshotResources(uuid)
      setNotice(result.retried > 0 ? `已重试 ${result.retried} 项` : '没有失败项。')
      await detail.refetch()
    } catch {
      setNotice('重试失败。')
    } finally {
      setRetrying(false)
    }
  }

  async function runCleanup(kind: SnapshotCleanupKind) {
    setCleaningKind(kind)
    setNotice(null)
    try {
      const result = await cleanupSnapshotResources(uuid, [kind])
      const removed = result.cleaned[kind] ?? 0
      setNotice(
        removed > 0
          ? `已清理${CLEANUP_KIND_TEXT[kind]} ${removed} 项，现占 ${formatBytes(result.storage.totalBytes)}。`
          : `没有可清理的内联${CLEANUP_KIND_TEXT[kind]}。`,
      )
      await Promise.all([detail.refetch(), storage.refetch()])
    } catch {
      setNotice('清理失败。')
    } finally {
      setCleaningKind(null)
    }
  }

  async function runRecapture() {
    setCapturing(true)
    setNotice(null)
    try {
      const result = await createSnapshotVersion(uuid)
      setNotice(result.deduplicated ? '内容未变化（已去重）。' : '已采集新版本。')
      await versions.refetch()
    } catch {
      setNotice('采集失败，旧版本不受影响。')
    } finally {
      setCapturing(false)
    }
  }

  async function runCompare() {
    if (active === null || compareWith === null) return
    setNotice(null)
    try {
      const result = await diffSnapshotVersions(uuid, active.versionId, compareWith)
      setNotice(result.diff || '两版本无差异。')
    } catch {
      setNotice('对比失败。')
    }
  }

  if (detail.isPending || detail.isError) return null
  const resources = detail.data.resources

  return (
    <div
      className="mt-1 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-2 text-xs"
      data-lumi-snapshot-diagnostics=""
    >
      <p className="flex items-center gap-1 font-medium text-[var(--lumi-text-secondary)]">
        <Activity aria-hidden className="size-3.5" />
        资源诊断（{resources.length}
        {detail.data.resourcesTruncated ? '+' : ''}）
      </p>
      {/* N124：资源预算 + 按类清理（只删选中类别；条目本体不受影响）。 */}
      {storage.isPending ? (
        <p className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">资源预算计算中…</p>
      ) : storage.isError ? (
        <p role="alert" className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">
          资源预算加载失败。
          <button type="button" className="ml-1 underline" onClick={() => void storage.refetch()}>
            重试
          </button>
        </p>
      ) : (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--lumi-text-secondary)]" data-lumi-snapshot-storage="">
          <span>
            共 {formatBytes(storage.data.totalBytes)}
          </span>
          <span aria-hidden>·</span>
          <span>图片 {storage.data.breakdown.images.count} 项（{formatBytes(storage.data.breakdown.images.bytes)}）</span>
          <span aria-hidden>·</span>
          <span>样式 {formatBytes(storage.data.breakdown.styles.bytes)}</span>
          <span aria-hidden>·</span>
          <span>附件 {formatBytes(storage.data.breakdown.attachments.bytes)}</span>
          {CLEANUP_KINDS.map((kind) => {
            const bucket = storage.data.breakdown[kind]
            if (bucket.bytes <= 0) return null
            return (
              <Button
                key={kind}
                size="sm"
                variant="ghost"
                disabled={cleaningKind !== null}
                onClick={() => void runCleanup(kind)}
              >
                {cleaningKind === kind ? (
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                ) : (
                  <Trash2 aria-hidden className="size-3.5" />
                )}
                清理{CLEANUP_KIND_TEXT[kind]}
              </Button>
            )
          })}
        </div>
      )}
      <ul className="mt-1 max-h-24 overflow-y-auto">
        {resources.map((resource, index) => (
          <li key={`${resource.url}-${index}`} className="flex items-baseline gap-2">
            <span
              className={cx(
                resource.status === 'failed' && 'text-[var(--lumi-danger)]',
                resource.status === 'ok' && 'text-[var(--lumi-success)]',
                resource.status === 'missing' && 'text-[var(--lumi-danger)]',
                resource.status === 'skipped' && 'text-[var(--lumi-text-tertiary)]',
              )}
            >
              {RESOURCE_STATUS_TEXT[resource.status] ?? resource.status}
            </span>
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-tertiary)]" title={resource.url}>
              {resource.url}
            </span>
          </li>
        ))}
        {resources.length === 0 ? (
          <li className="text-[var(--lumi-text-tertiary)]">没有资源记录。</li>
        ) : null}
      </ul>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant="ghost" onClick={() => void runRetry()} disabled={retrying}>
          {retrying ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <RotateCcw aria-hidden className="size-3.5" />}
          重试失败项
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void runRecapture()} disabled={capturing}>
          {capturing ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
          采集新版本
        </Button>
        {list.length > 1 ? (
          <>
            <select
              aria-label="选择版本"
              value={active?.versionId ?? ''}
              onChange={(e) => setSelected(Number(e.target.value))}
              className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              {list.map((version) => (
                <option key={version.versionId} value={version.versionId}>
                  {version.createdAt.slice(0, 16)} · {version.sha8}
                </option>
              ))}
            </select>
            <select
              aria-label="对比版本"
              value={compareWith ?? ''}
              onChange={(e) => setCompareWith(e.target.value === '' ? null : Number(e.target.value))}
              className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
            >
              <option value="">对比…</option>
              {list.map((version) => (
                <option key={version.versionId} value={version.versionId}>
                  {version.sha8}
                </option>
              ))}
            </select>
            <Button size="sm" variant="ghost" onClick={() => void runCompare()} disabled={compareWith === null}>
              <GitCompare aria-hidden className="size-3.5" />
              对比
            </Button>
          </>
        ) : null}
      </div>
      {notice ? (
        <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-1.5 text-[11px] text-[var(--lumi-text-secondary)]" data-lumi-snapshot-notice="">
          {notice}
        </pre>
      ) : null}
    </div>
  )
}
