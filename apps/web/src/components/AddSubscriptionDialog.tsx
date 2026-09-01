/** AddSubscriptionDialog — 0013 Gate 2：直接 RSS/Atom 预览 + 添加订阅。
 *
 * 用户闭环：输入直接 feed URL → 预览（无副作用）→ 真实 metadata →
 * 选择真实分类 → 确认 → FreshRSS subscribe → invalidate → 列表出现新 feed。
 *
 * 边界（0013 Spec + Gate 2 指令）：
 * - 只接受直接 RSS/Atom 地址；普通网页地址（preview 报 not_a_feed）时
 *   诚实提示「网站来源发现属于后续 Source Discovery」，不做 rel=alternate
 *   自动发现、不猜 /feed、不抓网页；
 * - preview 走 POST /api/v1/feed-preview（BFF safe-fetch boundary 保证
 *   无副作用与 SSRF 防护），subscribe 走 Gate 1 的 POST /api/v1/subscriptions
 *   （server-confirmed success）；
 * - 分类选择用真实 GET /api/v1/categories（含空分类）；
 * - mutation 后只 invalidate TanStack Query（feeds/categories/entries），
 *   不做 optimistic updates，不建第二套 subscription cache；
 * - 桌面/移动复用同一 Dialog primitive（fullscreenOnMobile），
 *   不创建第二套 modal framework；
 * - a11y：Escape 关闭、焦点 trap/还焦（Dialog primitive 内建）、
 *   表单 label 关联、44px 触控目标、双击防重（isPending 禁用）。 */

import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, ExternalLink, Loader2, Rss } from 'lucide-react'
import {
  useCategories,
  useFeedPreviewMutation,
  useSubscribeMutation,
} from '../api/queries'
import type { FeedPreviewMetadata } from '../api/types'
import { isDirectFeedUrl } from '../lib/direct-feed-url'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Select } from './ui/Select'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const FORMAT_LABEL: Record<FeedPreviewMetadata['format'], string> = {
  rss: 'RSS',
  atom: 'Atom',
}

/** 按错误 type 生成诚实文案（BFF message 是英文技术细节，仅作补充）。 */
function previewErrorText(error: unknown): { title: string; detail: string | null } {
  const type = (error as { type?: string } | null)?.type
  switch (type) {
    case 'not_a_feed':
      return {
        title: '这不是有效的 RSS / Atom 地址',
        detail: '当前请填写直接 RSS / Atom 地址；网站来源发现属于后续 Source Discovery。',
      }
    case 'unsafe_feed_url':
      return { title: '该地址不允许访问', detail: null }
    case 'feed_fetch_error':
      return { title: '无法获取该地址', detail: '可能是网络超时或目标服务器不可达，请稍后重试。' }
    case 'feed_too_large':
      return { title: '该内容过大', detail: null }
    case 'invalid_feed_url':
      return { title: '地址格式无效', detail: '请填写完整的 http(s) RSS / Atom 地址。' }
    case 'subscription_conflict':
      return { title: '已经订阅了这个源，无需重复添加。', detail: null }
    default:
      return { title: '预览失败', detail: null }
  }
}

export default function AddSubscriptionDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [url, setUrl] = useState('')
  const [localHint, setLocalHint] = useState<string | null>(null)
  const [preview, setPreview] = useState<FeedPreviewMetadata | null>(null)
  const [categoryId, setCategoryId] = useState('')
  const [subscribed, setSubscribed] = useState(false)

  const previewMutation = useFeedPreviewMutation()
  const subscribeMutation = useSubscribeMutation()
  // 分类列表只在打开时拉取（真实分类；空分类也列出）
  const categories = useCategories(open)

  // 打开时重置全部本地状态（上一次会话不留残留）
  useEffect(() => {
    if (open) {
      setUrl('')
      setLocalHint(null)
      setPreview(null)
      setCategoryId('')
      setSubscribed(false)
      previewMutation.reset()
      subscribeMutation.reset()
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const busy =
    previewMutation.isPending || subscribeMutation.isPending || subscribed

  function startPreview() {
    const value = url.trim()
    if (!value) return
    if (!isDirectFeedUrl(value)) {
      // 普通网页/非 http(s)：本地诚实提示（不发请求）
      setLocalHint(
        '当前请填写直接 RSS / Atom 地址；网站来源发现属于后续 Source Discovery。',
      )
      return
    }
    setLocalHint(null)
    setPreview(null)
    previewMutation.mutate(value, {
      onSuccess: (metadata) => setPreview(metadata),
    })
  }

  function confirmSubscribe() {
    if (!preview || preview.alreadySubscribed) return
    subscribeMutation.mutate(
      {
        feedUrl: preview.feedUrl,
        categoryId: categoryId || null,
      },
      { onSuccess: () => setSubscribed(true) },
    )
  }

  function close() {
    if (busy) return // 提交中不允许误关（mutation 仍在进行）
    onClose()
  }

  const error =
    previewMutation.error ??
    (subscribeMutation.isError ? subscribeMutation.error : null)
  const errorText = error !== null ? previewErrorText(error) : null

  return (
    <Dialog
      open={open}
      onClose={close}
      title="添加订阅"
      fullscreenOnMobile
      panelClassName="max-w-lg"
      footer={
        <>
          {!subscribed && (
            <Button variant="ghost" onClick={close} disabled={busy}>
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
          ) : (
            <Button
              variant="primary"
              onClick={confirmSubscribe}
              disabled={busy || preview.alreadySubscribed}
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
          )}
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (preview === null) startPreview()
          else confirmSubscribe()
        }}
        className="flex flex-col gap-4"
      >
        {/* URL 输入：预览成功后只读展示（当前预览对象锁定为该 URL） */}
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

        {/* 预览 / 订阅错误（loading 之外才显示，避免闪现） */}
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

        {/* 预览成功：真实 metadata + 分类选择 */}
        {preview !== null && (
          <div className="flex flex-col gap-4">
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
                  <span className="block text-xs text-[var(--lumi-text-tertiary)]">
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
            {preview.alreadySubscribed && (
              <div
                role="status"
                className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-secondary)]"
              >
                <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent)]" />
                已经订阅了这个源，无需重复添加。
              </div>
            )}

            {!preview.alreadySubscribed && (
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
                      {
                        value: '',
                        label: '默认分类（不指定）',
                      },
                      ...(categories.data ?? []).map((c) => ({
                        value: c.id,
                        label: c.label,
                      })),
                    ]}
                  />
                )}
              </div>
            )}
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
      </form>
    </Dialog>
  )
}
