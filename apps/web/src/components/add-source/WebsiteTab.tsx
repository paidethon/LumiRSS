/** WebsiteTab — 添加来源 · 网站发现模式（0014）。
 *
 * 用户闭环：输入普通网站 URL → POST /api/v1/source-discovery（无副作用）
 * → 候选列表（rel=alternate 声明 + 有界常见端点探测）→ 选择 →
 * POST /api/v1/feed-preview 验证 → 共享 PreviewStage（分类 + 订阅）。
 *
 * 边界：发现能力由 BFF safe-fetch 边界保证（SSRF 防护、有界响应、
 * 有界探测）；浏览器不抓网页、不猜路径。 */

import { useEffect, useState } from 'react'
import { AlertCircle, ChevronRight, Globe, Loader2, Rss } from 'lucide-react'
import {
  useFeedPreviewMutation,
  useSourceDiscoveryMutation,
  useSubscribeMutation,
} from '../../api/queries'
import type { DiscoveryCandidate, FeedPreviewMetadata } from '../../api/types'
import { managementErrorText } from '../../lib/management-errors'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'
import { PreviewStage } from './PreviewStage'
import type { AddSourceTabProps } from './DirectFeedTab'

const SOURCE_LABEL: Record<DiscoveryCandidate['source'], string> = {
  declared: '页面声明',
  probed: '常见端点',
}

export function WebsiteTab({ onClose, registerGuard }: AddSourceTabProps) {
  const [url, setUrl] = useState('')
  const [candidates, setCandidates] = useState<DiscoveryCandidate[] | null>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [preview, setPreview] = useState<FeedPreviewMetadata | null>(null)
  const [subscribed, setSubscribed] = useState(false)

  const discoveryMutation = useSourceDiscoveryMutation()
  const previewMutation = useFeedPreviewMutation()
  const subscribeMutation = useSubscribeMutation()

  const busy =
    discoveryMutation.isPending ||
    previewMutation.isPending ||
    subscribeMutation.isPending ||
    subscribed
  // 关闭防护只挡 pending（成功后允许 Escape / 完成关闭）
  const pending =
    discoveryMutation.isPending ||
    previewMutation.isPending ||
    subscribeMutation.isPending

  useEffect(() => {
    registerGuard(() => !pending)
    return () => registerGuard(null)
  }, [pending, registerGuard])

  function startDiscovery() {
    const value = url.trim()
    if (!value) return
    setCandidates(null)
    setPreview(null)
    discoveryMutation.mutate(value, {
      onSuccess: (result) => {
        setCandidates(result.candidates)
        setSelectedIndex(0)
      },
    })
  }

  function startPreview(candidate: DiscoveryCandidate) {
    setPreview(null)
    previewMutation.mutate(candidate.feedUrl, {
      onSuccess: (metadata) => setPreview(metadata),
    })
  }

  function backToCandidates() {
    setPreview(null)
    previewMutation.reset()
  }

  const discoveryError = discoveryMutation.error
  const discoveryErrorText =
    discoveryError !== null ? managementErrorText(discoveryError) : null

  return (
    <div className="flex flex-col gap-4">
      {preview === null && candidates === null && (
        <>
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="add-source-website-url"
              className="text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              网站地址
            </label>
            <input
              id="add-source-website-url"
              type="url"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className={cx(
                'min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
                'bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]',
                'placeholder:text-[var(--lumi-text-tertiary)]',
                'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
              )}
            />
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              自动发现该网站声明或常见位置上的 RSS / Atom 订阅源（不会抓取网页内容）。
            </p>
          </div>

          {/* 发现 loading */}
          {discoveryMutation.isPending && (
            <div className="flex flex-col gap-2" aria-label="正在发现订阅源">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          )}

          {/* 发现错误 */}
          {discoveryErrorText !== null && !discoveryMutation.isPending && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">{discoveryErrorText.title}</span>
                {discoveryErrorText.detail !== null && (
                  <span className="mt-0.5 block text-xs opacity-80">
                    {discoveryErrorText.detail}
                  </span>
                )}
              </span>
            </div>
          )}
        </>
      )}

      {/* 候选列表（发现成功后） */}
      {candidates !== null && preview === null && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
            发现 {candidates.length} 个候选订阅源
          </p>
          <div role="radiogroup" aria-label="候选订阅源" className="flex flex-col gap-2">
            {candidates.map((candidate, index) => (
              <label
                key={candidate.feedUrl}
                className={cx(
                  'flex min-h-14 cursor-pointer items-center gap-3 rounded-[var(--lumi-radius-md)] border px-3.5 py-2.5',
                  'transition-colors duration-[var(--lumi-motion-fast)]',
                  index === selectedIndex
                    ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)]'
                    : 'border-[var(--lumi-border)] bg-[var(--lumi-surface)] hover:bg-[var(--lumi-surface-hover)]',
                )}
              >
                <input
                  type="radio"
                  name="add-source-candidate"
                  value={candidate.feedUrl}
                  checked={index === selectedIndex}
                  onChange={() => setSelectedIndex(index)}
                  className="sr-only"
                />
                <span
                  aria-hidden
                  className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-elevated)] text-[var(--lumi-accent)]"
                >
                  <Rss className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                    {candidate.title ?? candidate.feedUrl}
                  </span>
                  <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                    {SOURCE_LABEL[candidate.source]}
                    {candidate.format !== null ? ` · ${candidate.format.toUpperCase()}` : ''}
                    {' · '}
                    {candidate.feedUrl}
                  </span>
                </span>
                <ChevronRight
                  aria-hidden
                  className={cx(
                    'size-4 shrink-0',
                    index === selectedIndex
                      ? 'text-[var(--lumi-accent)]'
                      : 'text-[var(--lumi-text-tertiary)]',
                  )}
                />
              </label>
            ))}
          </div>
        </div>
      )}

      {/* 预览 loading（选中候选后） */}
      {previewMutation.isPending && (
        <div className="flex flex-col gap-2" aria-label="正在获取订阅源信息">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-full" />
        </div>
      )}

      {/* 预览失败：候选不可用（回到候选列表重选） */}
      {previewMutation.error !== null && !previewMutation.isPending && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
        >
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block font-medium">
              {managementErrorText(previewMutation.error).title}
            </span>
            <span className="mt-0.5 block text-xs opacity-80">
              这个候选可能已失效，可以换一个候选重试。
            </span>
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
          onBack={backToCandidates}
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
        ) : preview !== null ? null : candidates === null ? (
          <Button
            variant="primary"
            onClick={startDiscovery}
            disabled={busy || url.trim() === ''}
          >
            {discoveryMutation.isPending ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                发现中…
              </>
            ) : (
              '发现'
            )}
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={() => startPreview(candidates[selectedIndex])}
            disabled={busy || candidates.length === 0}
          >
            <Globe aria-hidden className="size-4" />
            预览
          </Button>
        )}
      </div>
    </div>
  )
}
