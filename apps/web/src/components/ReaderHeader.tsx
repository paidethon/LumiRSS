import { Check, ExternalLink, Loader2, Star } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useEntryStateMutation } from '../api/queries'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { IconButton } from './ui/IconButton'
import { Tooltip } from './ui/Tooltip'
import { cx } from './ui/cx'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatPublishedAt(value: string | null): string {
  if (value === null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date)
}

/** ReaderHeader — 标题 / 元信息 / 工具栏（0009 Gate 3 视觉重建）。
 *
 * 布局（Spec Task 12）：紧凑工具栏（IconButton 32px + Tooltip）+
 * 强标题（27px 级，Folo 实测锚点）+ 弱化元信息行。原 0006 的两个
 * 大按钮（标记已读/收藏）改为工具栏图标按钮——set 语义、共用
 * mutation 实例、pending 双禁用、key=entryRef 防泄漏等行为全部保留
 * （在 Reader.tsx 上挂 key）。
 *
 * 行为不变式（Spec 硬边界 3/5）：
 * - set 语义（PATCH 目标状态，非 toggle）；
 * - 打开原文只放行绝对 http/https（safeExternalHttpUrl），
 *   target=_blank + rel=noopener noreferrer。 */
export default function ReaderHeader({ detail }: { detail: EntryDetail }) {
  const mutation = useEntryStateMutation()

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  return (
    <header className="border-b border-[var(--lumi-separator)] pb-5">
      {/* 元信息行（弱化）：来源 · 作者 · 时间 */}
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        {detail.feedTitle}
        {detail.author !== null && <span> · {detail.author}</span>}
        {published !== '' && <span> · {published}</span>}
      </p>

      {/* 强标题（Folo 锚点 27px/700；移动端略小） */}
      <h1 className="mt-2 text-[1.7rem] font-bold leading-snug text-[var(--lumi-text-primary)] max-lg:text-2xl max-lg:leading-tight">
        {detail.title}
      </h1>

      {/* 工具栏：紧凑图标按钮（桌面 32px，手机 touch 44px）。
          pending 时统一转圈，双按钮禁用（同一篇同时最多一个 PATCH）。 */}
      <div className="mt-4 flex items-center gap-1.5">
        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.read ? '标记为未读' : '标记为已读'}>
            <IconButton
              icon={
                <Check
                  aria-hidden
                  className={cx(
                    detail.read
                      ? 'text-[var(--lumi-accent)]'
                      : 'text-current',
                  )}
                />
              }
              label={detail.read ? '标记为未读' : '标记为已读'}
              aria-pressed={detail.read}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { read: !detail.read },
                })
              }
            />
          </Tooltip>
        )}

        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.starred ? '取消收藏' : '收藏'}>
            <IconButton
              icon={
                <Star
                  aria-hidden
                  className={cx(
                    detail.starred &&
                      'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]',
                  )}
                />
              }
              label={detail.starred ? '取消收藏' : '收藏'}
              aria-pressed={detail.starred}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { starred: !detail.starred },
                })
              }
            />
          </Tooltip>
        )}

        {articleUrl !== null && (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ExternalLink aria-hidden className="size-3.5" />
            打开原文
          </a>
        )}
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-[var(--lumi-danger)]" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
    </header>
  )
}
