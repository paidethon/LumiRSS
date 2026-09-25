/** N022 路由健康一键自检卡（RssHubTab 预览成功后的时间线头部）。
 *
 * 单个按钮并行调用既有面，Web 侧聚合为一张判定卡：
 * - 预览：POST /rsshub/preview（现跑一次；失败类诚实呈现）；
 * - 最近运行：GET /rsshub/routes/history（N025，x/y ok）；
 * - 缓存：预览响应的 cache.ageS/fresh（N027 缓存面）；
 * - 依赖：预览响应的 requires chips（N023；未知路由 → null 诚实呈现）。
 * 各分区独立渲染：一个面失败 → 该分区显示失败原因，其余分区仍如实
 * 展示（诚实部分结果）。分区判定项是跳转链接（滚动到对应区域）。
 */

import { useMutation } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { AlertCircle, CheckCircle2, HeartPulse, Loader2 } from 'lucide-react'
import { previewRssHub } from '../api/client'
import { useRssHubRouteHistory } from '../api/queries'
import type { RssHubPreviewMetadata, RssHubRequires, RssHubRouteRun } from '../api/types'
import { formatCacheAge, summarizeRouteRuns } from '../lib/rsshub-health'
import { managementErrorText } from '../lib/management-errors'
import { rsshubFailureClassLabel } from '../lib/rsshub-params'
import { Button } from './ui/Button'
import { cx } from './ui/cx'
import { RssHubRequiresChips } from './rsshub-requires-chips'

interface PreviewCacheInfo {
  ageS?: number | null
  fresh?: boolean
}

interface PreviewOk {
  kind: 'ok'
  preview: RssHubPreviewMetadata & { cache?: PreviewCacheInfo; requires?: RssHubRequires | null }
}

type PreviewState =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | PreviewOk
  | { kind: 'failed'; message: string; failureClass: string | null }

function jumpTo(elementId: string) {
  const el = document.getElementById(elementId)
  if (el === null) return
  const reduceMotion =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  el.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' })
}

function VerdictRow({
  id,
  label,
  verdict,
  verdictTone,
  jumpTargetId,
  children,
}: {
  id: string
  label: string
  verdict: string
  verdictTone: 'ok' | 'failed' | 'muted'
  jumpTargetId: string
  children?: ReactNode
}) {
  return (
    <div id={id} className="flex min-h-8 flex-wrap items-center gap-2" data-testid={`route-check-${label}`}>
      <span className="w-16 shrink-0 text-xs text-[var(--lumi-text-tertiary)]">{label}</span>
      <button
        type="button"
        onClick={() => jumpTo(jumpTargetId)}
        className={cx(
          'rounded-[var(--lumi-radius-sm)] px-1.5 py-0.5 text-xs font-medium underline-offset-2',
          'hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          verdictTone === 'ok' && 'text-[var(--lumi-success)]',
          verdictTone === 'failed' && 'text-[var(--lumi-danger)]',
          verdictTone === 'muted' && 'text-[var(--lumi-text-secondary)]',
        )}
        aria-label={`${label}：${verdict}，查看详情`}
      >
        {verdict}
      </button>
      {children !== undefined && <div className="min-w-0 flex-1">{children}</div>}
    </div>
  )
}

export function RsshubRouteHealthCard({
  routeId,
  params,
  routeKey,
}: {
  routeId: string
  params: Record<string, string>
  routeKey: string | null
}) {
  const historyQuery = useRssHubRouteHistory(routeKey)
  const [previewState, setPreviewState] = useState<PreviewState>({ kind: 'idle' })

  const checkMutation = useMutation({
    mutationFn: async () => {
      setPreviewState({ kind: 'pending' })
      // 三个面并行：预览（自带缓存年龄 + 依赖）+ 最近运行（N025 时间线）。
      const previewPromise = previewRssHub(routeId, params)
      const historyPromise =
        routeKey !== null ? historyQuery.refetch() : Promise.resolve({} as unknown)
      const [preview, history] = await Promise.allSettled([previewPromise, historyPromise])
      return { preview, history }
    },
    onSuccess: ({ preview }) => {
      if (preview.status === 'fulfilled') {
        setPreviewState({ kind: 'ok', preview: preview.value })
        return
      }
      const error = preview.reason
      setPreviewState({
        kind: 'failed',
        message:
          error instanceof Error
            ? managementErrorText(error).title
            : '预览失败（地址不可达或非法）',
        failureClass: null,
      })
    },
  })

  const runs: RssHubRouteRun[] = historyQuery.data?.items ?? []
  const runsSummary = summarizeRouteRuns(runs)
  // idle = 从未自检；pending/ok/failed 都展示判定行（pending 行如实显示
  // 「检查中…」，重新自检时保留旧值区域并逐面刷新）。
  const checked = previewState.kind !== 'idle'

  return (
    <section
      aria-label="路由一键自检"
      data-testid="route-health-card"
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
          <HeartPulse aria-hidden className="size-3.5" />
          一键自检
        </p>
        <Button
          size="sm"
          variant="secondary"
          disabled={checkMutation.isPending}
          data-testid="route-check-run"
          onClick={() => checkMutation.mutate()}
        >
          {checkMutation.isPending ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <HeartPulse aria-hidden className="size-3.5" />
          )}
          {checkMutation.isPending ? '自检中…' : checked ? '重新自检' : '开始自检'}
        </Button>
      </div>
      {!checked ? (
        <p className="mt-1.5 text-xs text-[var(--lumi-text-tertiary)]">
          并行检查预览 / 最近运行 / 缓存 / 依赖，聚合为一张判定卡。
        </p>
      ) : (
        <div className="mt-1.5 flex flex-col gap-0.5">
          <VerdictRow
            id="rsshub-check-preview"
            label="预览"
            verdict={
              previewState.kind === 'pending'
                ? '检查中…'
                : previewState.kind === 'ok'
                  ? 'ok'
                  : `失败${
                      previewState.failureClass !== null
                        ? `（${rsshubFailureClassLabel(previewState.failureClass)}）`
                        : ''
                    }`
            }
            verdictTone={previewState.kind === 'ok' ? 'ok' : previewState.kind === 'failed' ? 'failed' : 'muted'}
            jumpTargetId="rsshub-check-preview"
          >
            {previewState.kind === 'failed' && (
              <span className="flex min-w-0 items-center gap-1 text-[11px] text-[var(--lumi-danger)]">
                <AlertCircle aria-hidden className="size-3 shrink-0" />
                <span className="truncate">{previewState.message}</span>
              </span>
            )}
            {previewState.kind === 'ok' && (
              <span className="flex min-w-0 items-center gap-1 text-[11px] text-[var(--lumi-text-tertiary)]">
                <CheckCircle2 aria-hidden className="size-3 shrink-0" />
                <span className="truncate">
                  {previewState.preview.title !== '' ? previewState.preview.title : 'feed 可达'}
                </span>
              </span>
            )}
          </VerdictRow>
          <VerdictRow
            id="rsshub-check-runs"
            label="最近运行"
            verdict={
              historyQuery.isError
                ? '加载失败'
                : runsSummary.total === 0
                  ? '暂无记录'
                  : `${runsSummary.ok}/${runsSummary.total} ok`
            }
            verdictTone={
              historyQuery.isError
                ? 'failed'
                : runsSummary.total > 0 && runsSummary.failed === 0
                  ? 'ok'
                  : 'muted'
            }
            jumpTargetId="rsshub-route-runs"
          />
          <VerdictRow
            id="rsshub-check-cache"
            label="缓存"
            verdict={
              previewState.kind === 'ok'
                ? formatCacheAge(previewState.preview.cache)
                : previewState.kind === 'pending'
                  ? '检查中…'
                  : '—'
            }
            verdictTone={previewState.kind === 'ok' ? 'ok' : 'muted'}
            jumpTargetId="rsshub-check-preview"
          />
          <VerdictRow
            id="rsshub-check-deps"
            label="依赖"
            verdict={previewState.kind === 'ok' ? '见右侧' : '未知'}
            verdictTone={previewState.kind === 'ok' ? 'ok' : 'muted'}
            jumpTargetId="rsshub-check-preview"
          >
            {previewState.kind === 'ok' && (
              <RssHubRequiresChips requires={previewState.preview.requires ?? null} />
            )}
          </VerdictRow>
        </div>
      )}
    </section>
  )
}
