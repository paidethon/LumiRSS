/** RagIndexPage — RAG 索引页（section='rag'；侧栏「RAG 索引」入口）。
 *
 * R24：把索引从设置项升级为真正的内容页——当前账号索引集合的真实
 * 总览 + 操作面。总览数值全部来自 GET /api/v1/rag/index/overview
 * （数量/模型/磁盘/队列/失败明细，绝不渲染原始 embedding）。
 *
 * - 总览卡：文档/分块/模型维度/最近更新/磁盘占用/队列进度条；
 * - 「处理完任务 ≠ 全部成功」：queue.failed > 0 时显式警示 + 失败项
 *   列表（原因 + 单独重试）+ 全部重试；
 * - 操作行（Toolbar）：选择来源（DetailDrawer 内逐来源勾选，复用
 *   RagExclusionsPanel）、增量索引、重建、暂停/继续（本账号增量）、
 *   取消重建（仅作业进行中；取消 = 既有 F093 暂停语义）、删除索引
 *   （确认框明示不删原文）；
 * - 检索试验：复用 RagTrySearchPanel（真实 /rag/search，命中分数 +
 *   内容预览 + 点击 resolveAndOpen 跳正文）；
 * - 页内「设置」深链 settings 'ai' 分类（全局模型/连接配置仍在设置）；
 * - loading / empty / error 三态齐备；所有网络状态有对应 UI。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Database,
  Pause,
  Play,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  Trash2,
  Zap,
} from 'lucide-react'
import type { ToolbarAction } from '../ui/Toolbar'
import { pauseRagRebuild, rebuildRag } from '../../api/client'
import {
  convergeRagIndex,
  deleteRagIndex,
  getRagIndexOverview,
  pauseRagIndexIncremental,
  resumeRagIndexIncremental,
  retryFailedRagIndex,
  type RagIndexOverview,
  type RagIndexRetryFailedResult,
} from '../../api/rag-index'
import { formatTimestamp } from '../../lib/date-format'
import { RagExclusionsPanel, RagTrySearchPanel } from '../RagW5Panels'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { DetailDrawer } from '../ui/DetailDrawer'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { Toolbar } from '../ui/Toolbar'
import { cx } from '../ui/cx'
import { requestOpenSettings } from '../settings/settings-bridge'

/** 语料 kind → 展示名（未知 kind 原样回显，绝不编造）。 */
const KIND_LABELS: Record<string, string> = {
  rss: 'RSS 条目',
  clip: '剪藏',
  snapshot: '网页快照',
  obsidian_note: 'Obsidian 笔记',
  note: '笔记',
  newsletter: '邮件简报',
  inbox: '收件箱',
  api_source: 'API 来源',
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function RagIndexPage() {
  const overview = useQuery({
    queryKey: ['rag-index-overview'],
    queryFn: ({ signal }) => getRagIndexOverview(signal),
  })
  const actions = useRagIndexActions()
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  if (overview.isPending) {
    return (
      <div className="flex min-h-0 flex-1 flex-col" aria-label="RAG 索引加载中">
        <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[calc(4.75rem_+_var(--safe-bottom))]">
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="mt-3 h-40 w-full" />
          </div>
        </div>
      </div>
    )
  }

  if (overview.isError || overview.data === undefined) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[calc(4.75rem_+_var(--safe-bottom))]">
          <EmptyState
            icon={<AlertTriangle aria-hidden className="size-6 text-[var(--lumi-danger)]" />}
            title="索引总览加载失败"
            description={
              overview.error instanceof Error ? overview.error.message : '请稍后重试。'
            }
            action={
              <Button variant="secondary" size="sm" onClick={() => void overview.refetch()}>
                重试
              </Button>
            }
          />
        </div>
      </div>
    )
  }

  const data = overview.data
  const jobRunning = data.job?.status === 'running'

  const toolbar: ToolbarAction[] = [
    {
      id: 'sources',
      label: '选择来源',
      icon: <SlidersHorizontal aria-hidden className="size-3.5" />,
      onSelect: () => setSourcesOpen(true),
    },
    {
      id: 'converge',
      label: '增量索引',
      icon: <Zap aria-hidden className="size-3.5" />,
      onSelect: () => actions.converge.mutate(),
      disabled: actions.converge.isPending || data.incrementalPaused,
    },
    {
      id: 'rebuild',
      label: '重建',
      icon: <RefreshCw aria-hidden className="size-3.5" />,
      onSelect: () => actions.rebuild.mutate(),
      disabled: actions.rebuild.isPending,
    },
    jobRunning
      ? {
          id: 'cancel',
          label: '取消重建',
          icon: <Pause aria-hidden className="size-3.5" />,
          onSelect: () => actions.cancel.mutate(),
          disabled: actions.cancel.isPending,
        }
      : data.incrementalPaused
        ? {
            id: 'resume',
            label: '继续',
            icon: <Play aria-hidden className="size-3.5" />,
            onSelect: () => actions.resume.mutate(),
            disabled: actions.resume.isPending,
          }
        : {
            id: 'pause',
            label: '暂停',
            icon: <Pause aria-hidden className="size-3.5" />,
            onSelect: () => actions.pause.mutate(),
            disabled: actions.pause.isPending,
          },
    {
      id: 'delete',
      label: '删除索引',
      icon: <Trash2 aria-hidden className="size-3.5" />,
      onSelect: () => setDeleteOpen(true),
      danger: true,
    },
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-3 max-lg:pb-[calc(4.75rem_+_var(--safe-bottom))]">
        <PageHeaderBlock />

        {!data.enabled && data.documents === 0 ? (
          <NotEnabledState />
        ) : (
          <>
            <Toolbar aria-label="RAG 索引操作" className="mt-3" actions={toolbar} />
            <OperationStatus actions={actions} />
            <OverviewCard data={data} />
            <FailuresSection data={data} />
            <section
              aria-label="检索试验"
              className="mt-3 flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
            >
              <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
                检索试验
              </h2>
              <p className="text-xs text-[var(--lumi-text-secondary)]">
                输入查询试检索当前索引；点击命中行跳转正文。
              </p>
              <RagTrySearchPanel enabled={data.enabled} />
            </section>
          </>
        )}
      </div>

      <DetailDrawer
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        title="选择索引来源"
      >
        <div className="flex flex-col gap-2">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            逐来源决定是否纳入语义索引；排除会立即移除该来源现有分块，原文不受影响。
          </p>
          <RagExclusionsPanel />
        </div>
      </DetailDrawer>

      <DeleteIndexDialog open={deleteOpen} data={data} onClose={() => setDeleteOpen(false)} />
    </div>
  )
}

// ---- 头部 + 空态 -------------------------------------------------------------

function PageHeaderBlock() {
  return (
    <div className="flex min-w-0 items-start justify-between gap-2">
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold leading-tight text-[var(--lumi-text-primary)]">
          RAG 索引
        </h1>
        <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          本账号语义索引的真实状态；全局模型与连接配置在设置中。
        </p>
      </div>
      <Button
        variant="secondary"
        size="sm"
        className="max-lg:min-h-11 shrink-0"
        onClick={() => requestOpenSettings('ai')}
      >
        <Settings aria-hidden className="size-3.5" />
        设置
      </Button>
    </div>
  )
}

function NotEnabledState() {
  return (
    <EmptyState
      icon={<Database aria-hidden className="size-6 text-[var(--lumi-text-tertiary)]" />}
      title="语义索引未启用"
      description="启用后内容会逐步进入语义索引；启用与模型配置在设置中的 AI 分类。"
      action={
        <Button variant="primary" size="sm" onClick={() => requestOpenSettings('ai')}>
          <Settings aria-hidden className="size-3.5" />
          去设置启用
        </Button>
      }
      className="mt-6"
    />
  )
}

// ---- 操作 mutations + 状态行 ---------------------------------------------------

/** 页面级操作 mutation 集：增量索引 / 重建 / 取消重建 / 暂停 / 继续。 */
function useRagIndexActions() {
  const queryClient = useQueryClient()
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rag-index-overview'] })
    await queryClient.invalidateQueries({ queryKey: ['rag-status'] })
  }
  const converge = useMutation({
    mutationFn: () => convergeRagIndex(),
    onSuccess: invalidate,
  })
  const rebuild = useMutation({
    mutationFn: () => rebuildRag(),
    onSuccess: invalidate,
  })
  const cancel = useMutation({
    mutationFn: () => pauseRagRebuild(),
    onSuccess: invalidate,
  })
  const pause = useMutation({
    mutationFn: () => pauseRagIndexIncremental(),
    onSuccess: invalidate,
  })
  const resume = useMutation({
    mutationFn: () => resumeRagIndexIncremental(),
    onSuccess: invalidate,
  })
  return { converge, rebuild, cancel, pause, resume }
}

function OperationStatus({ actions }: { actions: ReturnType<typeof useRagIndexActions> }) {
  const { converge, rebuild, cancel, pause, resume } = actions
  const error =
    converge.error ?? rebuild.error ?? cancel.error ?? pause.error ?? resume.error
  return (
    <div aria-live="polite" className="flex flex-col gap-0.5">
      {converge.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          增量索引进行中…
        </p>
      )}
      {converge.data !== undefined && !converge.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {converge.data.skipped != null
            ? '本轮收敛已跳过（索引未启用或已暂停）。'
            : `本轮收敛：新索引 ${converge.data.indexed} 篇，清理失效 ${converge.data.swept} 篇。`}
        </p>
      )}
      {rebuild.data !== undefined && !rebuild.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          上次重建：{rebuild.data.chunks} 块 · {(rebuild.data.elapsedMs / 1000).toFixed(1)}s
        </p>
      )}
      {cancel.data !== undefined && !cancel.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {cancel.data.paused
            ? '将在当前批完成后暂停（可稍后从断点续建）。'
            : '当前没有进行中的重建。'}
        </p>
      )}
      {pause.data !== undefined && !pause.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          已暂停本账号的增量索引。
        </p>
      )}
      {resume.data !== undefined && !resume.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          已恢复本账号的增量索引。
        </p>
      )}
      {error instanceof Error && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          操作失败：{error.message}
        </p>
      )}
    </div>
  )
}

// ---- 总览卡 -------------------------------------------------------------------

function OverviewCard({ data }: { data: RagIndexOverview }) {
  const queue = data.queue
  const total = queue.done + queue.pending
  const pct = total > 0 ? Math.round((queue.done / total) * 100) : 0
  return (
    <section
      aria-label="索引总览"
      className="mt-3 flex flex-col gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex items-center gap-2">
        <Database aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">索引总览</h2>
        {data.incrementalPaused && (
          <span className="ml-auto text-xs text-[var(--lumi-warning)]">增量索引已暂停</span>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs max-sm:grid-cols-1">
        <OverviewStat label="文档" value={String(data.documents)} />
        <OverviewStat label="分块" value={String(data.chunks)} />
        <OverviewStat label="嵌入模型" value={`${data.modelId}（${data.dim} 维）`} />
        <OverviewStat
          label="最近更新"
          value={formatTimestamp(data.lastUpdatedAt) || '从未'}
        />
        <OverviewStat
          label="磁盘占用"
          value={formatBytes(data.storage.totalBytes)}
          hint={data.storage.basis === 'dbstat' ? '按页实测' : '按载荷字节'}
        />
        <OverviewStat
          label="已排除来源"
          value={String(data.excludedFeeds + data.aiDisabledFeeds)}
          hint={data.aiDisabledFeeds > 0 ? `含 AI 禁用 ${data.aiDisabledFeeds}` : undefined}
        />
      </dl>

      {data.sources.length > 0 && (
        <ul
          aria-label="索引来源"
          className="flex flex-wrap gap-1.5"
          data-rag-index-sources=""
        >
          {data.sources.map((source) => (
            <li
              key={source.kind}
              className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)]"
            >
              {kindLabel(source.kind)}：{source.indexedDocs}/{source.corpusDocs} 篇 ·{' '}
              {source.chunks} 块
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-1">
        <div
          role="progressbar"
          aria-label="索引队列进度"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={queue.done}
          className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--lumi-surface-pressed)]"
        >
          <div
            className={cx(
              'h-full rounded-full bg-[var(--lumi-accent)]',
              'transition-[width] duration-150 motion-reduce:transition-none',
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-xs text-[var(--lumi-text-secondary)]" data-rag-index-queue="">
          队列：待处理 {queue.pending} · 已完成 {queue.done}
          {queue.failed > 0 && (
            <span className="text-[var(--lumi-danger)]"> · 失败 {queue.failed}</span>
          )}
          {queue.stale > 0 && <span> · 待更新 {queue.stale}</span>}
        </p>
      </div>

      {data.calendarPaused && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          实例级任务日历已暂停增量索引：全账号收敛暂时停止（管理员操作）。
        </p>
      )}
      {data.lastError !== null && data.lastError !== '' && (
        <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
          上次错误：{data.lastError}
        </p>
      )}
    </section>
  )
}

function OverviewStat({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="shrink-0 text-[var(--lumi-text-tertiary)]">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium text-[var(--lumi-text-primary)]">
        {value}
        {hint !== undefined && (
          <span className="ml-1 font-normal text-[var(--lumi-text-tertiary)]">
            （{hint}）
          </span>
        )}
      </dd>
    </div>
  )
}

// ---- 失败项 -------------------------------------------------------------------

function FailuresSection({ data }: { data: RagIndexOverview }) {
  const queryClient = useQueryClient()
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rag-index-overview'] })
    await queryClient.invalidateQueries({ queryKey: ['rag-status'] })
  }
  const retryAll = useMutation({
    mutationFn: (): Promise<RagIndexRetryFailedResult> => retryFailedRagIndex(),
    onSuccess: invalidate,
  })
  const retryOne = useMutation({
    mutationFn: (ref: string): Promise<RagIndexRetryFailedResult> =>
      retryFailedRagIndex([ref]),
    onSuccess: invalidate,
  })
  const retryError = retryAll.isError ? retryAll.error : retryOne.isError ? retryOne.error : null
  const lastResult = retryAll.data ?? retryOne.data

  if (data.queue.failed === 0 && data.failures.length === 0) return null

  return (
    <section
      aria-label="失败项"
      className="mt-3 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-danger)] p-3"
    >
      <div className="flex min-h-11 items-center justify-between gap-2 lg:min-h-0">
        <p className="flex items-center gap-1.5 text-sm text-[var(--lumi-danger)]">
          <AlertTriangle aria-hidden className="size-3.5 shrink-0" />
          处理完成 ≠ 全部成功：{data.queue.failed} 项失败
        </p>
        <Button
          variant="secondary"
          size="sm"
          className="max-lg:min-h-11 shrink-0"
          loading={retryAll.isPending}
          onClick={() => retryAll.mutate()}
        >
          全部重试
        </Button>
      </div>
      <ul className="flex flex-col gap-1.5" data-rag-index-failures="">
        {data.failures.map((failure) => (
          <li
            key={`${failure.ref ?? 'job'}:${failure.reason.slice(0, 16)}`}
            className="flex items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
          >
            <div className="min-w-0">
              <p className="truncate font-medium text-[var(--lumi-text-primary)]">
                {failure.ref ?? '作业级错误'}
              </p>
              <p className="mt-0.5 text-[var(--lumi-text-secondary)]">{failure.reason}</p>
            </div>
            {failure.ref != null && (
              <Button
                variant="ghost"
                size="sm"
                className="max-lg:min-h-11 shrink-0"
                loading={retryOne.isPending && retryOne.variables === failure.ref}
                onClick={() => retryOne.mutate(failure.ref as string)}
              >
                重试
              </Button>
            )}
          </li>
        ))}
      </ul>
      {lastResult !== undefined && !retryAll.isPending && !retryOne.isPending && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {retryResultText(lastResult)}
        </p>
      )}
      {retryError instanceof Error && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          重试失败：{retryError.message}
        </p>
      )}
    </section>
  )
}

function retryResultText(result: RagIndexRetryFailedResult): string {
  if (result.requested === 0) return '当前没有可重试的失败项。'
  const parts = [`请求 ${result.requested} 项`, `成功 ${result.updated} 项`]
  if (result.missing.length > 0) parts.push(`${result.missing.length} 项原文已不存在`)
  return parts.join('，')
}

// ---- 删除确认 -----------------------------------------------------------------

function DeleteIndexDialog({
  open,
  data,
  onClose,
}: {
  open: boolean
  data: RagIndexOverview
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const del = useMutation({
    mutationFn: () => deleteRagIndex(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rag-index-overview'] })
      await queryClient.invalidateQueries({ queryKey: ['rag-status'] })
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="删除索引"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={del.isPending}>
            取消
          </Button>
          <Button
            variant="danger"
            size="sm"
            loading={del.isPending}
            onClick={() => del.mutate()}
          >
            删除索引
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-2 text-sm text-[var(--lumi-text-primary)]">
        <p>
          将清空本账号的全部索引分块与向量
          {data.chunks > 0 ? `（当前约 ${data.chunks} 块）` : ''}。
        </p>
        <p className="font-medium text-[var(--lumi-danger)]" data-delete-keeps-sources="">
          原文不会被删除：RSS 条目、剪藏、快照等原始内容全部保留，索引可随时重建。
        </p>
        {del.data !== undefined && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            已删除 {del.data.removedChunks} 块分块、{del.data.removedVecRows} 行向量。
          </p>
        )}
        {del.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            删除失败：{del.error instanceof Error ? del.error.message : '请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

export default RagIndexPage
