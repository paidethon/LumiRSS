/** UnsubscribeDialog — 0013 Gate 3：取消订阅（破坏性操作，双重确认）。
 *
 * 流程：⋯ 菜单 → 取消订阅 → 本对话框（明确显示 Feed 名 + N012 影响
 * 预览）→「取消订阅」→ 再次确认（红色最终确认 + 返回）→ DELETE
 * mutation → server confirm → invalidate。不做 optimistic updates。
 *
 * N012：对话框打开即拉取只读影响预览（工作区引用/看板状态/RSS 书签/
 * 批注/未读/收件箱规则；计数如实、样本有界）。最终确认按钮在预览
 * 到达前禁用（确认前必见影响）。工件选择（keep_artifacts）：
 * - true（默认）：保留批注与工作区引用（冻结 ref 以 stale 卡片呈现）；
 * - false：退订同时清理批注与该来源的工作区引用/看板状态。
 *
 * 诚实边界：不承诺「历史文章会保留」（FreshRSS 行为未在 Lumi 内验证，
 * 不写没验证的结论）；文案只陈述确定事实：订阅会被移除、不再接收更新。 */

import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, Rss, Trash2 } from 'lucide-react'
import {
  useUnsubscribeMutation,
  useUnsubscribePreviewQuery,
} from '../api/queries'
import type { Subscription } from '../api/types'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

function ImpactList({
  label,
  count,
  items,
  sampleLimit,
}: {
  label: string
  count: number
  items: string[]
  sampleLimit: number
}) {
  if (count === 0) return null
  return (
    <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs">
      <span className="font-medium text-[var(--lumi-text-primary)]">{label}</span>
      <span className="ml-1.5 text-[var(--lumi-text-secondary)]">{count} 项</span>
      {items.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-[var(--lumi-text-tertiary)]">
          {items.map((item, index) => (
            <li key={index} className="truncate">
              {item}
            </li>
          ))}
          {count > items.length && <li>… 其余 {count - items.length} 项略（样本 ≤ {sampleLimit}）</li>}
        </ul>
      )}
    </li>
  )
}

export default function UnsubscribeDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  subscription: Subscription | null
}) {
  // confirm：第一层（显示 Feed 名 + 影响预览）→ final：再次确认
  const [stage, setStage] = useState<'confirm' | 'final'>('confirm')
  // N012：退订后工件保留与否（默认保留）
  const [keepArtifacts, setKeepArtifacts] = useState(true)
  const mutation = useUnsubscribeMutation()
  const previewQuery = useUnsubscribePreviewQuery(
    open && subscription !== null ? subscription.subscriptionRef : null,
  )
  const preview = previewQuery.data ?? null

  useEffect(() => {
    if (open) {
      setStage('confirm')
      setKeepArtifacts(true)
      mutation.reset()
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const busy = mutation.isPending

  function close() {
    if (busy) return // 删除进行中不允许误关
    onClose()
  }

  function confirmUnsubscribe() {
    if (!subscription || busy) return
    if (previewQuery.isPending) return // 确认门：预览未到达不放行
    mutation.mutate(
      { subscriptionRef: subscription.subscriptionRef, keepArtifacts },
      { onSuccess: onClose },
    )
  }

  const errorText = mutation.isError ? managementErrorText(mutation.error) : null

  return (
    <Dialog
      open={open}
      onClose={close}
      title={stage === 'confirm' ? '取消订阅' : '再次确认'}
      footer={
        stage === 'confirm' ? (
          <>
            <Button variant="ghost" onClick={close} disabled={busy}>
              保持订阅
            </Button>
            <Button variant="secondary" onClick={() => setStage('final')} disabled={busy}>
              取消订阅
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={() => setStage('confirm')} disabled={busy}>
              返回
            </Button>
            <Button
              variant="danger"
              onClick={confirmUnsubscribe}
              disabled={busy || previewQuery.isPending}
              aria-describedby={previewQuery.isPending ? 'unsubscribe-preview-gate' : undefined}
            >
              {busy ? (
                <>
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                  取消订阅中…
                </>
              ) : (
                <>
                  <Trash2 aria-hidden className="size-4" />
                  确认取消订阅
                </>
              )}
            </Button>
          </>
        )
      }
    >
      {subscription !== null && (
        <div className="flex flex-col gap-4">
          {/* 明确显示 Feed 名 + URL（操作对象一目了然） */}
          <div className="flex items-center gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
            <span
              aria-hidden
              className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]"
            >
              <Rss className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                {subscription.title}
              </span>
              <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                {subscription.feedUrl}
              </span>
            </span>
          </div>

          {/* N012：退订影响预览（只读；确认前必见） */}
          <section aria-label="退订影响预览" className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">退订影响预览</p>
            {previewQuery.isPending && (
              <p
                id="unsubscribe-preview-gate"
                role="status"
                className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]"
              >
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
                正在统计该来源牵连的批注与整理结构…
              </p>
            )}
            {previewQuery.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-text-tertiary)]">
                影响预览加载失败（不影响退订本身）；请自行确认该来源没有需要保留的批注。
              </p>
            )}
            {preview !== null && (
              <ul className="flex flex-col gap-1" data-testid="unsubscribe-impact">
                <ImpactList
                  label="工作区引用"
                  count={preview.workspaceItems.count}
                  items={preview.workspaceItems.items.map(
                    (item) => `${item.workspaceName || item.workspaceId}`,
                  )}
                  sampleLimit={preview.sampleLimit}
                />
                <ImpactList
                  label="看板状态"
                  count={preview.boardItems.count}
                  items={preview.boardItems.items.map((item) => item.status)}
                  sampleLimit={preview.sampleLimit}
                />
                <ImpactList
                  label="RSS 书签"
                  count={preview.libraryItems.count}
                  items={preview.libraryItems.items.map((item) => item.title)}
                  sampleLimit={preview.sampleLimit}
                />
                <ImpactList
                  label="批注"
                  count={preview.annotations.count}
                  items={preview.annotations.items.map((item) => item.excerpt)}
                  sampleLimit={preview.sampleLimit}
                />
                <ImpactList
                  label="投影未读"
                  count={preview.unreadCount}
                  items={[]}
                  sampleLimit={preview.sampleLimit}
                />
                <ImpactList
                  label="命中的收件箱规则"
                  count={preview.inboxRules.count}
                  items={preview.inboxRules.items.map((item) => item.value)}
                  sampleLimit={preview.sampleLimit}
                />
                {preview.workspaceItems.count === 0 &&
                  preview.boardItems.count === 0 &&
                  preview.libraryItems.count === 0 &&
                  preview.annotations.count === 0 &&
                  preview.unreadCount === 0 &&
                  preview.inboxRules.count === 0 && (
                    <li className="text-xs text-[var(--lumi-text-tertiary)]">
                      没有发现牵连的批注或整理结构。
                    </li>
                  )}
              </ul>
            )}
          </section>

          <p className="text-sm text-[var(--lumi-text-secondary)]">
            将从 FreshRSS 移除「{subscription.title}
            」的订阅，之后不再接收该源的更新。这是一个破坏性操作。
          </p>

          {/* N012：工件保留选择（预览可见时展示） */}
          {preview !== null && (
            <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2.5">
              <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                <input
                  type="checkbox"
                  checked={keepArtifacts}
                  onChange={(e) => setKeepArtifacts(e.target.checked)}
                />
                保留批注与工作区引用（退订后以「来源不可用」呈现）
              </label>
              <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
                {keepArtifacts
                  ? '取消订阅后，该来源的批注与工作区引用保留（条目不再可用时会显示为缺失卡片）。'
                  : '取消订阅的同时清理该来源的批注与工作区引用/看板状态；RSS 书签保留。'}
              </p>
            </div>
          )}

          {stage === 'final' && (
            <div
              role="alert"
              className={cx(
                'flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]',
              )}
            >
              <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">确定要取消订阅吗？</span>
                <span className="mt-0.5 block text-xs opacity-80">
                  此操作无法在 Lumi 内撤销；如需重新订阅，可再次添加该地址。
                </span>
              </span>
            </div>
          )}

          {errorText !== null && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
            >
              <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">{errorText.title}</span>
                {errorText.detail !== null && (
                  <span className="mt-0.5 block text-xs opacity-80">{errorText.detail}</span>
                )}
              </span>
            </div>
          )}
        </div>
      )}
    </Dialog>
  )
}
