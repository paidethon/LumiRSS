/** UnsubscribeDialog — 0013 Gate 3：取消订阅（破坏性操作，双重确认）。
 *
 * 流程：⋯ 菜单 → 取消订阅 → 本对话框（明确显示 Feed 名）→「取消订阅」
 * → 再次确认（红色最终确认 + 返回）→ DELETE mutation → server confirm
 * → invalidate。不做 optimistic updates。
 *
 * 诚实边界：不承诺「历史文章会保留」（FreshRSS 行为未在 Lumi 内验证，
 * 不写没验证的结论）；文案只陈述确定事实：订阅会被移除、不再接收更新。 */

import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, Rss, Trash2 } from 'lucide-react'
import { useUnsubscribeMutation } from '../api/queries'
import type { Subscription } from '../api/types'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

export default function UnsubscribeDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  subscription: Subscription | null
}) {
  // confirm：第一层（显示 Feed 名）→ final：再次确认
  const [stage, setStage] = useState<'confirm' | 'final'>('confirm')
  const mutation = useUnsubscribeMutation()

  useEffect(() => {
    if (open) {
      setStage('confirm')
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
    mutation.mutate(
      { subscriptionRef: subscription.subscriptionRef },
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
            <Button variant="danger" onClick={confirmUnsubscribe} disabled={busy}>
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
              className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent)]"
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

          <p className="text-sm text-[var(--lumi-text-secondary)]">
            将从 FreshRSS 移除「{subscription.title}
            」的订阅，之后不再接收该源的更新。这是一个破坏性操作。
          </p>

          {stage === 'final' && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
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
