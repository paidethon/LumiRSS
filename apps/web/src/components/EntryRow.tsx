import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { dateTimeFormatter as dateFormatter } from '../lib/date-format'
import { EntryActionButtons } from './EntryActionButtons'
import { cx } from './ui/cx'

function formatPublishedAt(value: string | null): string {
  if (value === null) {
    return '—'
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : dateFormatter.format(date)
}

/** EntryRow — Timeline 桌面行（0009 Gate 2 重建；0011 修正补充重构）。
 *
 * 信息层级（0011 §16，现有 API 字段内的最大近似）：
 *   第一行：来源 · 作者(可选) · 时间        [◷ 稍后读 ☆ 收藏]
 *   第二行：标题（未读 medium；已读 normal）
 *
 * 0011 修正补充：
 * - 行根从 button 改 div[role=row] + 标题区 button——动作区（稍后读/
 *   收藏）与行点击平级共存，不再嵌套 button（§15/§16）；
 * - 动作区由 EntryActionButtons 共享组件渲染（hover 弱显 + 激活常显，
 *   §17/§18；预留稳定空间，hover 零跳动）。
 *
 * 状态表达不只靠颜色（AC10）：未读=字重+左侧 accent 圆点；选中=
 * selected surface + accent 圆点常亮；连续列表（无卡片、无行阴影）。 */
export default function EntryRow({
  item,
  selected,
}: {
  item: EntryListItem
  selected: boolean
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const dimRead = useAppSettings((s) => s.settings.dimRead)

  return (
    <div
      data-entry-ref={item.entryRef}
      className={cx(
        'group/row flex w-full flex-col gap-1 px-4 py-3 text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)]',
      )}
    >
      {/* 元信息行：来源 · 作者 · 时间 + 动作区（稍后读/收藏） */}
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        {/* 标题点击区（flex-1）：打开 Reader；与右侧动作区平级不嵌套 */}
        <button
          type="button"
          onClick={() => selectEntry(item.entryRef)}
          aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-[var(--lumi-radius-md)] text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          {/* 未读标记圆点是产品固定视觉语义（状态不只靠颜色） */}
          <span
            aria-hidden="true"
            className={cx(
              'size-1.5 shrink-0 rounded-full',
              item.read ? 'bg-transparent' : 'bg-[var(--lumi-accent)]',
            )}
          />
          <span className="truncate font-medium">{item.feedTitle}</span>
          {item.author !== null && (
            <span className="hidden truncate lg:inline">· {item.author}</span>
          )}
          <span className="ml-auto shrink-0">{formatPublishedAt(item.publishedAt)}</span>
        </button>
        <EntryActionButtons entryRef={item.entryRef} starred={item.starred} compact />
      </div>

      {/* 标题：未读 medium/primary，已读 normal/secondary；桌面单行 truncate。 */}
      <button
        type="button"
        onClick={() => selectEntry(item.entryRef)}
        aria-pressed={selected}
        className={cx(
          'min-w-0 rounded-[var(--lumi-radius-md)] text-left text-sm lg:truncate',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          item.read
            ? 'font-normal text-[var(--lumi-text-secondary)]'
            : 'font-medium text-[var(--lumi-text-primary)]',
        )}
        title={item.title}
      >
        {item.title}
      </button>
    </div>
  )
}
