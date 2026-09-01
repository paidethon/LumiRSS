/** DirectFeedTab — 添加来源 · 直接 RSS/Atom 模式（0013 AddSubscriptionDialog
 * 逻辑迁移，行为不变；0014 起成为三模式之一）。
 *
 * 用户闭环：输入直接 feed URL → 预览（无副作用）→ 真实 metadata →
 * 选择真实分类 → 确认 → FreshRSS subscribe → invalidate → 列表出现新 feed。
 *
 * 边界：只接受直接 RSS/Atom 地址；普通网页地址本地诚实提示「切换到
 * 网站标签页」（0014 起不再属于后续 milestone——发现能力就在隔壁 tab）。 */

import { useEffect, useState } from 'react'
import { AlertCircle, Loader2 } from 'lucide-react'
import { useFeedPreviewMutation, useSubscribeMutation } from '../../api/queries'
import type { FeedPreviewMetadata } from '../../api/types'
import { isDirectFeedUrl } from '../../lib/direct-feed-url'
import { managementErrorText } from '../../lib/management-errors'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'
import { PreviewStage } from './PreviewStage'

export interface AddSourceTabProps {
  /** 对话框级受防护的关闭（busy 时拒绝，取消/完成/Escape/遮罩共用） */
  onClose: () => void
  /** 注册关闭防护谓词：返回 false = busy 拒绝关闭 */
  registerGuard: (fn: (() => boolean) | null) => void
}

export function DirectFeedTab({ onClose, registerGuard }: AddSourceTabProps) {
  const [url, setUrl] = useState('')
  const [localHint, setLocalHint] = useState<string | null>(null)
  const [preview, setPreview] = useState<FeedPreviewMetadata | null>(null)
  const [subscribed, setSubscribed] = useState(false)

  const previewMutation = useFeedPreviewMutation()
  const subscribeMutation = useSubscribeMutation()

  const busy =
    previewMutation.isPending || subscribeMutation.isPending || subscribed
  // 关闭防护只挡 pending（成功后允许 Escape / 完成关闭）
  const pending =
    previewMutation.isPending || subscribeMutation.isPending

  useEffect(() => {
    registerGuard(() => !pending)
    return () => registerGuard(null)
  }, [pending, registerGuard])

  function startPreview() {
    const value = url.trim()
    if (!value) return
    if (!isDirectFeedUrl(value)) {
      // 普通网页/非 http(s)：本地诚实提示（不发请求）；发现能力在网站 tab
      setLocalHint('请填写直接 RSS / Atom 地址；如果是普通网站，请切换到「网站」标签页。')
      return
    }
    setLocalHint(null)
    setPreview(null)
    previewMutation.mutate(value, {
      onSuccess: (metadata) => setPreview(metadata),
    })
  }

  const error = previewMutation.error
  const errorText = error !== null ? managementErrorText(error) : null

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="add-subscription-url"
          className="text-sm font-medium text-[var(--lumi-text-primary)]"
        >
          RSS / Atom 地址
        </label>
        <input
          id="add-subscription-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={url}
          readOnly={preview !== null || subscribed}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/feed.xml"
          aria-describedby={localHint !== null ? 'add-subscription-hint' : undefined}
          className={cx(
            'min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
            'bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]',
            'placeholder:text-[var(--lumi-text-tertiary)]',
            'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            'read-only:opacity-80',
          )}
        />
        {localHint !== null && (
          <p
            id="add-subscription-hint"
            role="status"
            className="text-xs text-[var(--lumi-text-secondary)]"
          >
            {localHint}
          </p>
        )}
      </div>

      {/* 预览 loading */}
      {previewMutation.isPending && (
        <div className="flex flex-col gap-2" aria-label="正在获取订阅源信息">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-full" />
        </div>
      )}

      {/* 预览错误（loading 之外才显示，避免闪现） */}
      {errorText !== null && !previewMutation.isPending && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
        >
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block font-medium">{errorText.title}</span>
            {errorText.detail !== null && (
              <span className="mt-0.5 block text-xs opacity-80">{errorText.detail}</span>
            )}
          </span>
        </div>
      )}

      {/* 预览成功：共享 预览 → 分类 → 订阅 阶段 */}
      {preview !== null && (
        <PreviewStage
          preview={preview}
          subscribeMutation={subscribeMutation}
          subscribed={subscribed}
          onSubscribed={() => setSubscribed(true)}
        />
      )}

      {/* 底部操作区 */}
      <div className="mt-1 flex justify-end gap-2">
        {!subscribed && (
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            取消
          </Button>
        )}
        {subscribed ? (
          <Button variant="primary" onClick={onClose}>
            完成
          </Button>
        ) : preview === null ? (
          <Button
            variant="primary"
            onClick={startPreview}
            disabled={busy || url.trim() === ''}
          >
            {previewMutation.isPending ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                预览中…
              </>
            ) : (
              '预览'
            )}
          </Button>
        ) : null}
      </div>
    </div>
  )
}
