import { Star } from 'lucide-react'
import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
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
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

/** EntryRow — Timeline 行（0009 Gate 2 重建）。
 *
 * Folo 式信息层级（现有 API 字段内的最大近似，缺 favicon/摘要/缩略图
 * 时优雅降级——契约缺口已记录给 0010+，不在前端伪造）：
 *
 *   第一行：来源 feedTitle · 作者(可选) · 时间        [★ 收藏标记]
 *   第二行：标题（未读=primary 字重 500；已读=secondary 常规）
 *
 * 状态表达不只靠颜色（AC10）：未读=字重+左侧 accent 圆点；选中=
 * selected surface + accent 圆点常亮；收藏=星形图标。
 * 连续列表（无卡片、无行阴影）；hover=中性 surface；选中=低透明
 * surface（非浓色大填充）。 */
export default function EntryRow({
  item,
  selected,
}: {
  item: EntryListItem
  selected: boolean
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  // 0010 Gate B：未读圆点开关（设置中心真实生效；关闭后未读状态仍由
  // 字重差异承载——不只靠颜色，可读性不受影响）
  const showUnreadDot = useAppSettings((s) => s.settings.timelineUnreadDot)
  // 0010a Gate E：已读变暗（AC6）——整体降低不透明度，字重差异保留
  const dimRead = useAppSettings((s) => s.settings.dimRead)

  return (
    <button
      type="button"
      onClick={() => selectEntry(item.entryRef)}
      aria-pressed={selected}
      data-entry-ref={item.entryRef}
      className={cx(
        'flex w-full flex-col gap-1 px-4 py-3 text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)]',
      )}
    >
      {/* 元信息行：来源 · 作者 · 时间 + 收藏星标 */}
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        {/* 未读圆点：非颜色冗余信号之一（与字重互补）；设置可关闭 */}
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
        {item.author !== null && (
          <span className="hidden truncate lg:inline">· {item.author}</span>
        )}
        <span className="ml-auto shrink-0">{formatPublishedAt(item.publishedAt)}</span>
        {item.starred && (
          <Star
            aria-label="已收藏"
            className="size-3.5 shrink-0 fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]"
          />
        )}
      </div>

      {/* 标题：未读 medium/primary，已读 normal/secondary（不只靠颜色：
          字重差异在两种主题下都可见）。
          0007 语义保留：手机 wrap（最多 3 行），桌面单行 truncate。 */}
      <span
        className={cx(
          'min-w-0 text-sm max-lg:line-clamp-3 lg:truncate',
          item.read
            ? 'font-normal text-[var(--lumi-text-secondary)]'
            : 'font-medium text-[var(--lumi-text-primary)]',
        )}
        title={item.title}
      >
        {item.title}
      </span>
    </button>
  )
}
