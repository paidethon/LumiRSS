/** RagSettingsSection — 设置 → AI → 语义检索（RAG）。
 *
 * P0-07/P0-12：enableRag/rebuildRag 的首批真实 UI 消费者（此前唯一
 * 展示是 Agent 工作台只读 chip，queries.ts 的「操作入口在设置页」注释
 * 由本节兑现）。职责：
 * - 状态：enabled / chunks / model / lastRebuildAt（诚实展示）；
 * - 启用：显式授权下载/加载嵌入模型（POST /rag/enable；fastembed 未
 *   安装时按钮禁用并说明原因——RagModelUnavailable 的 message 原样透出；
 *   契约无「关闭」端点，故不伪造关闭开关）；
 * - 重建：POST /rag/rebuild（有界长任务；busy 转圈 + 完成报告
 *   chunks/elapsedMs；重建进行中再次点击 → RagRebuildBusy message）；
 * - lastError：danger 小字诚实展示。
 * 所有 HTTP 经 src/api/client.ts；loading / error 态齐备。 */

import { AlertCircle, CheckCircle2, Database, Loader2, RefreshCw } from 'lucide-react'
import {
  useEnableRagMutation,
  useRagStatus,
  useRebuildRagMutation,
} from '../../api/queries'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

export function RagSettingsSection() {
  const status = useRagStatus()
  const enable = useEnableRagMutation()
  const rebuild = useRebuildRagMutation()

  if (status.isPending) {
    return (
      <div className="flex flex-col gap-2 py-3" aria-label="语义检索状态加载中">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    )
  }

  if (status.isError || status.data === undefined) {
    return (
      <div className="py-3">
        <div role="alert" className="flex items-center gap-1.5 text-sm text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5 shrink-0" />
          语义检索状态加载失败
        </div>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          {status.error instanceof Error ? status.error.message : '请稍后重试。'}
        </p>
        <Button size="sm" variant="secondary" className="mt-2" onClick={() => status.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const data = status.data
  const lastError = data.lastError !== null && data.lastError !== '' ? data.lastError : null

  return (
    <section aria-label="语义检索（RAG）" className="flex flex-col gap-3 py-3">
      <div className="flex items-center gap-2">
        <Database aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">语义检索（RAG）</h3>
        {data.enabled ? (
          <span className="ml-auto flex items-center gap-1 text-xs text-[var(--lumi-category-green)]">
            <CheckCircle2 aria-hidden className="size-3.5" />
            已启用
          </span>
        ) : (
          <span className="ml-auto text-xs text-[var(--lumi-text-tertiary)]">未启用</span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        启用后 Agent 回答会融合语义检索（fastembed 本地嵌入模型；首次启用需要
        下载模型）。索引只在本机 SQLite，重建为有界全量任务。
      </p>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs max-sm:grid-cols-1">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-[var(--lumi-text-tertiary)]">已索引块</dt>
          <dd className="font-medium text-[var(--lumi-text-primary)]">{data.chunks}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-[var(--lumi-text-tertiary)]">嵌入模型</dt>
          <dd className="truncate font-medium text-[var(--lumi-text-primary)]">{data.model}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-[var(--lumi-text-tertiary)]">上次重建</dt>
          <dd className="font-medium text-[var(--lumi-text-primary)]">
            {formatTimestamp(data.lastRebuildAt) || '从未'}
          </dd>
        </div>
      </dl>

      {/* 操作区：未启用 → 启用按钮；已启用 → 重建按钮（契约无关闭端点，
          不伪造关闭开关）。busy 状态 + 结果反馈 + 错误内联。 */}
      <div className="flex flex-wrap items-center gap-2">
        {!data.enabled && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => enable.mutate()}
            disabled={!data.fastembedAvailable || enable.isPending}
            title={
              data.fastembedAvailable
                ? undefined
                : 'fastembed 未安装（服务端缺少 rag extra），无法启用语义索引。'
            }
          >
            {enable.isPending && <Loader2 aria-hidden className="size-3.5 animate-spin" />}
            {enable.isPending ? '启用中…' : '启用语义检索'}
          </Button>
        )}
        <Button
          size="sm"
          variant="secondary"
          onClick={() => rebuild.mutate()}
          disabled={rebuild.isPending}
        >
          <RefreshCw aria-hidden className={cx('size-3.5', rebuild.isPending && 'animate-spin')} />
          {rebuild.isPending ? '重建中…' : '重建索引'}
        </Button>
        {rebuild.data !== undefined && !rebuild.isPending && (
          <span role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            上次重建：{rebuild.data.chunks} 块 · {(rebuild.data.elapsedMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      {!data.fastembedAvailable && (
        <p role="status" className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          当前服务端未安装 fastembed（部署需含 rag extra）：启用不可用，关键词检索不受影响。
        </p>
      )}

      {enable.isError && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          启用失败：{enable.error instanceof Error ? enable.error.message : '请稍后重试。'}
        </p>
      )}
      {rebuild.isError && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          重建失败：{rebuild.error instanceof Error ? rebuild.error.message : '请稍后重试。'}
        </p>
      )}
      {lastError !== null && (
        <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          上次错误：{lastError}
        </p>
      )}
    </section>
  )
}

export default RagSettingsSection
