import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { EntryActionButtons } from './EntryActionButtons'
import { cx } from './ui/cx'

/** EntryCard — 移动端共享卡片（0011 Gate 3；修正补充重构）。
 *
 * 首页与收藏页复用（Spec §11.2），层级在现有 API 字段内的最大近似：
 *
 *   第一行：来源（柔彩圆点）· 时间        [◷ 稍后读 ★ 收藏]
 *   第二行：标题（未读 medium；已读 normal，最多 3 行）
 *
 * 0011 修正补充：
 * - 卡根从 button 改 div + 标题区 button——动作区（44px 触控）与卡片
 *   点击平级共存（§19/§20：08:00 ◷ ★，icon + aria-label，无文字）；
 * - 动作区由 EntryActionButtons 渲染（触屏设备常显，§18）。
 *
 * 契约缺口诚实降级（Spec §8）：无摘要/缩略图 → 纯文本卡片。 */
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
    <div
      data-entry-ref={item.entryRef}
      className={cx(
        'group/row flex w-full flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] px-3.5 py-3 text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
      )}
    >
      {/* 元信息行：来源 + 时间 + 动作区（稍后读/收藏，触屏常显） */}
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
        <button
          type="button"
          onClick={() => selectEntry(item.entryRef)}
          aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-[var(--lumi-radius-md)] text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
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
        </button>
        <EntryActionButtons entryRef={item.entryRef} starred={item.starred} />
      </div>

      {/* 标题：未读 medium/primary，已读 normal/secondary；最多 3 行 */}
      <button
        type="button"
        onClick={() => selectEntry(item.entryRef)}
        aria-pressed={selected}
        className={cx(
          'min-w-0 rounded-[var(--lumi-radius-md)] text-left text-[15px] leading-snug line-clamp-3',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          item.read
            ? 'font-normal text-[var(--lumi-text-secondary)]'
            : 'font-medium text-[var(--lumi-text-primary)]',
        )}
      >
        {item.title}
      </button>
    </div>
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
