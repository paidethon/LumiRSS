import { Check, Clock, ExternalLink, Loader2, MessageSquare, Star } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useEntryStateMutation } from '../api/queries'
import { useToggleReadLater } from '../lib/read-later'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { formatReadingTime, textFromHtml } from '../lib/reading-time'
import { useAppSettings } from '../store/app-settings'
import ReaderAaPanel from './ReaderAaPanel'
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
export default function ReaderHeader({
  detail,
  onOpenAiConversation,
}: {
  detail: EntryDetail
  /** 0016：打开文章限定 AI 对话（由 Reader 持有面板开关状态）。 */
  onOpenAiConversation?: () => void
}) {
  const mutation = useEntryStateMutation()
  const { isReadLater, toggleReadLater } = useToggleReadLater()
  const readLaterMarked = isReadLater(detail.entryRef)
  const showReadingTime = useAppSettings((s) => s.settings.readerShowReadingTime)

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  // 0012 Gate 5：CJK 感知阅读时间（弱化展示；开关控制）。
  // 输入用 contentText（BFF 已产出的安全纯文本）优先，回退从
  // contentHtml 提取（本地 DOMParser，不进入渲染）。仅对不可信
  // HTML做只读解析，输出只有数字。文本量极小，不 memo。
  const readingTime = showReadingTime
    ? formatReadingTime(
        detail.contentText.trim() !== ''
          ? detail.contentText
          : textFromHtml(detail.contentHtml ?? ''),
      )
    : null

  return (
    <header className="border-b border-[var(--lumi-separator)] pb-5">
      {/* 元信息行（弱化）：来源 · 作者 · 时间 · 阅读时间 */}
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        {detail.feedTitle}
        {detail.author !== null && <span> · {detail.author}</span>}
        {published !== '' && <span> · {published}</span>}
        {readingTime !== null && <span> · {readingTime}</span>}
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
                      ? 'text-[var(--lumi-accent-text)]'
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

        {/* 稍后读（0011 修正补充 §21–§23）：✓ ◷ ☆ 顺序——阅读处理 →
            临时保存 → 长期收藏；本地 marker 零网络，即时切换（乐观）；
            始终可见（不依赖 hover）；active = accent icon + subtle bg，
            同一 Clock 图标不换形（§23）。 */}
        <Tooltip content={readLaterMarked ? '从稍后读移除' : '加入稍后读'}>
          <IconButton
            icon={
              <Clock
                aria-hidden
                className={cx(
                  readLaterMarked && 'fill-[var(--lumi-accent-soft)]',
                )}
              />
            }
            label={readLaterMarked ? '从稍后读移除' : '加入稍后读'}
            aria-pressed={readLaterMarked}
            touch
            className={readLaterMarked ? 'text-[var(--lumi-accent-text)]' : undefined}
            onClick={() => toggleReadLater(detail.entryRef)}
          />
        </Tooltip>

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

        {/* 0016：文章限定 AI 对话入口（右侧面板；Reader 持有开关） */}
        {onOpenAiConversation !== undefined && (
          <Tooltip content="AI 对话">
            <IconButton
              icon={<MessageSquare aria-hidden />}
              label="AI 对话"
              touch
              onClick={onOpenAiConversation}
            />
          </Tooltip>
        )}

        {/* 0012 Gate 7：Reader 内快速阅读样式面板（Aa）；与设置中心
            同一 settings source，不遮挡正文关键操作。 */}
        <ReaderAaPanel />
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-[var(--lumi-danger)]" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
    </header>
  )
}
