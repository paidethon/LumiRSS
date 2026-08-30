import { Star } from 'lucide-react'
import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { cx } from './ui/cx'

/** EntryCard — 移动端共享卡片（0011 Gate 3，参考图 05-home/02-favorites）。
 *
 * 首页与收藏页复用同一卡片组件（Spec §11.2），信息层级在现有 API
 * 字段内的最大近似：
 *
 *   第一行：来源 feedTitle（柔彩圆点）· 时间          [★ 已收藏]
 *   第二行：标题（未读 medium/primary；已读 normal/secondary，
 *           最多 3 行——0007 移动端语义保留）
 *
 * 契约缺口诚实降级（Spec §8）：无 excerpt/thumbnailUrl/readTime 字段
 * → 纯文本卡片，不留空洞占位；缩略图/摘要等契约归属后续里程碑，
 * 前端不加可选字段伪造。
 *
 * 状态语义不只靠颜色（AC10）：未读=字重 medium+圆点（圆点纯视觉
 * aria-hidden）；已读 dimRead 沿用 0010a 设置；星标为状态展示
 * （写入入口在 Reader 内，卡片不提供行内星标按钮——避免嵌套交互
 * 与列表点击冲突，参考图行内星标是展示位）。 */
export default function EntryCard({
  item,
  selected,
}: {
  item: EntryListItem
  selected: boolean
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const showUnreadDot = useAppSettings((s) => s.settings.timelineUnreadDot)
  const dimRead = useAppSettings((s) => s.settings.dimRead)

  return (
    <button
      type="button"
      onClick={() => selectEntry(item.entryRef)}
      aria-pressed={selected}
      data-entry-ref={item.entryRef}
      className={cx(
        'flex w-full flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] px-3.5 py-3 text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
      )}
    >
      {/* 元信息行：来源 + 时间 + 收藏星标 */}
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        {showUnreadDot && (
          <span
            aria-hidden="true"
            className={cx(
              'size-1.5 shrink-0 rounded-full',
              item.read ? 'bg-transparent' : 'bg-[var(--lumi-accent)]',
            )}
          />
        )}
        <span className="truncate font-medium">{item.feedTitle}</span>
        <span className="ml-auto shrink-0">{formatPublishedAt(item.publishedAt)}</span>
        {item.starred && (
          <Star
            aria-label="已收藏"
            className="size-3.5 shrink-0 fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]"
          />
        )}
      </div>

      {/* 标题：未读 medium/primary，已读 normal/secondary（字重差异
          承载状态语义，两种主题下都可见） */}
      <span
        className={cx(
          'min-w-0 text-[15px] leading-snug line-clamp-3',
          item.read
            ? 'font-normal text-[var(--lumi-text-secondary)]'
            : 'font-medium text-[var(--lumi-text-primary)]',
        )}
      >
        {item.title}
      </span>
    </button>
  )
}

const cardDateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})

function formatPublishedAt(value: string | null): string {
  if (value === null) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : cardDateFormatter.format(date)
}
