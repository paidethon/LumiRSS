/** PreviewStage — 0014 共享「预览 → 选分类 → 订阅」阶段。
 *
 * 三种添加模式（直接 RSS / 网站发现 / RSSHub）在拿到 preview 元数据后
 * 共用同一段 UI 与同一套 mutation（useSubscribeMutation，0013 管道）：
 * - 真实 metadata 卡片（标题 / 格式 / feedUrl / 描述 / siteUrl 外链）；
 * - alreadySubscribed 只读提示；
 * - 真实分类下拉（GET /api/v1/categories，含空分类，失败降级默认分类）；
 * - 确认添加 → POST /api/v1/subscriptions（server-confirmed success →
 *   invalidateSubscriptionState，由 useSubscribeMutation 完成）；
 * - 订阅成功后「已添加订阅」提示。
 *
 * 不做 optimistic updates、不建第二套订阅缓存——与 0013 完全一致。 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, ExternalLink, Loader2, Rss } from 'lucide-react'
import type { UseMutationResult } from '@tanstack/react-query'
import { useCategories } from '../../api/queries'
import type { FeedPreviewMetadata, Subscription } from '../../api/types'
import { managementErrorText } from '../../lib/management-errors'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'

const FORMAT_LABEL: Record<FeedPreviewMetadata['format'], string> = {
  rss: 'RSS',
  atom: 'Atom',
}

export interface PreviewStageProps {
  preview: FeedPreviewMetadata
  /** 由调用方创建并传下来（busy 状态需要归调用方掌握，用于关闭防护） */
  subscribeMutation: UseMutationResult<
    Subscription,
    Error,
    { feedUrl: string; categoryId?: string | null; title?: string | null }
  >
  subscribed: boolean
  onSubscribed: () => void
  /** 网站/RSSHub 模式：回到候选/路由选择 */
  onBack?: () => void
}

export function PreviewStage({
  preview,
  subscribeMutation,
  subscribed,
  onSubscribed,
  onBack,
}: PreviewStageProps) {
  const categories = useCategories(true)
  const [categoryId, setCategoryId] = useState('')

  function confirmSubscribe() {
    if (preview.alreadySubscribed || subscribeMutation.isPending) return
    subscribeMutation.mutate(
      {
        feedUrl: preview.feedUrl,
        categoryId: categoryId || null,
      },
      { onSuccess: onSubscribed },
    )
  }

  const errorText =
    subscribeMutation.error !== null ? managementErrorText(subscribeMutation.error) : null

  return (
    <div className="flex flex-col gap-4">
      {onBack !== undefined && (
        <button
          type="button"
          onClick={onBack}
          className="flex min-h-11 items-center gap-1 self-start text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          ← 重新选择
        </button>
      )}

      {/* 真实 metadata 卡片 */}
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent)]"
          >
            <Rss className="size-4" />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-[var(--lumi-text-primary)]">
              {preview.title}
            </span>
            <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
              {FORMAT_LABEL[preview.format]} · {preview.feedUrl}
            </span>
          </span>
        </div>
        {preview.description !== null && (
          <p className="mt-2.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {preview.description}
          </p>
        )}
        {preview.siteUrl !== null && (
          <p className="mt-2.5 flex items-center gap-1 text-xs text-[var(--lumi-text-tertiary)]">
            <ExternalLink aria-hidden className="size-3" />
            <a
              href={preview.siteUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate underline-offset-2 hover:underline"
            >
              {preview.siteUrl}
            </a>
          </p>
        )}
      </div>

      {/* 已订阅提示：只读，禁用「确认添加」 */}
      {preview.alreadySubscribed && !subscribed && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-secondary)]"
        >
          <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent)]" />
          已经订阅了这个源，无需重复添加。
        </div>
      )}

      {/* 订阅错误（不遮挡 loading） */}
      {errorText !== null && !subscribeMutation.isPending && (
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

      {/* 分类选择 + 确认添加 */}
      {!preview.alreadySubscribed && !subscribed && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="add-subscription-category"
              className="text-sm font-medium text-[var(--lumi-text-primary)]"
            >
              分类
            </label>
            {categories.isPending ? (
              <Skeleton className="h-11 w-full" aria-label="分类加载中" />
            ) : categories.isError ? (
              <div className="flex items-center justify-between gap-2 text-sm text-[var(--lumi-text-secondary)]">
                <span>分类加载失败，将添加到默认分类。</span>
                <Button size="sm" onClick={() => categories.refetch()}>
                  重试
                </Button>
              </div>
            ) : (
              <Select
                id="add-subscription-category"
                className="min-h-11 w-full"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
                options={[
                  { value: '', label: '默认分类（不指定）' },
                  ...(categories.data ?? []).map((c) => ({
                    value: c.id,
                    label: c.label,
                  })),
                ]}
              />
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Button
              variant="primary"
              onClick={confirmSubscribe}
              disabled={
                preview.alreadySubscribed ||
                subscribeMutation.isPending ||
                subscribed
              }
            >
              {subscribeMutation.isPending ? (
                <>
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                  添加中…
                </>
              ) : (
                '确认添加'
              )}
            </Button>
          </div>
        </div>
      )}

      {/* 订阅成功：新 feed 已出现（invalidate → refetch） */}
      {subscribed && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)]/30 bg-[var(--lumi-accent)]/10 px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]"
        >
          <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent)]" />
          <span className="min-w-0">
            <span className="block font-medium">已添加订阅</span>
            <span className="mt-0.5 block text-xs text-[var(--lumi-text-secondary)]">
              订阅列表已更新，稍候文章会陆续出现在时间线里。
            </span>
          </span>
        </div>
      )}
    </div>
  )
}
