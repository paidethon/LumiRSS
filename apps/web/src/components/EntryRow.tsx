import { memo, useRef, useState } from 'react'
import { CheckCheck, Clock, Star } from 'lucide-react'
import type { EntryListItem } from '../api/types'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings } from '../store/app-settings'
import { useEntryStateMutation } from '../api/queries'
import { useToggleReadLater } from '../lib/read-later'
import { recordRecentRead } from '../lib/recent-reads'
import {
  swipeIsVertical,
  swipePreviewOffset,
  swipePreviewOpacity,
  swipeShouldCommit,
  swipeStartAllowed,
} from '../lib/card-swipe'
import { formatListTime } from '../lib/date-format'
import { SourceGlyph, SourceLabel } from '../lib/source-meta'
import { EntryActionButtons } from './EntryActionButtons'
import { cx } from './ui/cx'

/** EntryRow — Timeline 桌面行（0009 Gate 2 重建；2026-09 移动端专项重构）。
 *
 * 信息层级（P2 统一 + F02/F04）：
 *   [☑] [●] [A] 来源 · 作者(可选) · 时间      [◷ 稍后读 ☆ 收藏]
 *       标题（未读 medium；已读 normal）
 *       摘要一行截断（F02，可关）
 *
 * - 来源缺失降级「来源未知」；有 feedUrl 时来源可点击进入该订阅范围；
 * - 密度（F01）由列表容器 data-density 驱动；
 * - 状态表达不只靠颜色：未读=字重+左侧 accent 圆点；选中=selected
 *   surface + accent 圆点常亮；连续列表（无卡片、无行阴影）；
 * - F07 多选：selectMode=true 时左侧出现 44px 复选框，点行 = 切换选中；
 * - F08 滑动：cardSwipeAction !== 'none' 时内容层 translateX 跟手 +
 *   背景动作层（与 EntryCard 同一语义，见 lib/card-swipe）；
 * - F10：打开文章时记录最近阅读（开关关闭时 lib 内部 no-op）。
 *
 * memo 边界：props 仅 item + selected + 多选回调（稳定引用）。 */
function EntryRow({
  item,
  selected,
  selectMode = false,
  checked = false,
  onToggleSelect,
}: {
  item: EntryListItem
  selected: boolean
  /** F07：多选模式（列表容器下发） */
  selectMode?: boolean
  /** F07：当前行是否已勾选 */
  checked?: boolean
  /** F07：点行/勾选框时切换选中（不打开文章） */
  onToggleSelect?: (entryRef: string) => void
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const dimRead = useAppSettings((s) => s.settings.dimRead)
  const showSnippet = useAppSettings((s) => s.settings.listShowSnippet)
  const timeFormat = useAppSettings((s) => s.settings.listTimeFormat)
  const cardSwipeAction = useAppSettings((s) => s.settings.cardSwipeAction)
  const { mutate: mutateEntryState } = useEntryStateMutation()
  const { toggleReadLater } = useToggleReadLater()

  // ---- F08 滑动手势（语义与 EntryCard 完全一致；见 lib/card-swipe） ----
  const swipeEnabled = cardSwipeAction !== 'none'
  const [swipeDx, setSwipeDx] = useState(0)
  const touchStartRef = useRef<{ x: number; y: number; tracking: boolean } | null>(null)
  const suppressClickRef = useRef(false)

  const onTouchStart = (event: React.TouchEvent) => {
    const touch = event.touches[0]
    if (!touch) return
    touchStartRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      tracking: swipeEnabled && swipeStartAllowed(touch.clientX),
    }
  }
  const onTouchMove = (event: React.TouchEvent) => {
    const start = touchStartRef.current
    if (start === null || !start.tracking) return
    const touch = event.touches[0]
    if (!touch) return
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    setSwipeDx(swipeIsVertical(dx, dy) ? 0 : swipePreviewOffset(dx))
  }
  const onTouchEnd = (event: React.TouchEvent) => {
    const start = touchStartRef.current
    touchStartRef.current = null
    setSwipeDx(0)
    if (start === null || !start.tracking) return
    const touch = event.changedTouches[0]
    const dx = touch !== undefined ? touch.clientX - start.x : 0
    const dy = touch !== undefined ? touch.clientY - start.y : 0
    if (!swipeShouldCommit(dx, dy)) return
    suppressClickRef.current = true
    if (cardSwipeAction === 'read') {
      mutateEntryState({ entryRef: item.entryRef, patch: { read: true } })
    } else if (cardSwipeAction === 'readLater') {
      toggleReadLater(item.entryRef)
    } else if (cardSwipeAction === 'star') {
      mutateEntryState({ entryRef: item.entryRef, patch: { starred: !item.starred } })
    }
  }

  /** 行主点击：多选模式切换选中；普通模式记录最近阅读 + 打开文章。 */
  const handleOpen = () => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false
      return
    }
    if (selectMode) {
      onToggleSelect?.(item.entryRef)
      return
    }
    recordRecentRead({
      entryRef: item.entryRef,
      feedTitle: item.feedTitle,
      title: item.title,
    })
    selectEntry(item.entryRef)
  }

  return (
    <div
      data-entry-ref={item.entryRef}
      onTouchStart={swipeEnabled ? onTouchStart : undefined}
      onTouchMove={swipeEnabled ? onTouchMove : undefined}
      onTouchEnd={swipeEnabled ? onTouchEnd : undefined}
      className={cx(
        'lumi-entry-row group/row relative flex w-full overflow-hidden text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)]',
      )}
    >
      {/* F08 动作背景层 */}
      {swipeEnabled && swipeDx !== 0 && (
        <div
          aria-hidden="true"
          data-swipe-action-hint={cardSwipeAction}
          className={cx(
            'pointer-events-none absolute inset-y-0 flex items-center gap-1.5 bg-[var(--lumi-accent-soft)] px-5 text-xs font-medium text-[var(--lumi-accent-text)]',
            swipeDx > 0 ? 'left-0 justify-start' : 'right-0 justify-end',
          )}
          style={{ opacity: swipePreviewOpacity(swipeDx) }}
        >
          {cardSwipeAction === 'read' && <CheckCheck aria-hidden className="size-4" />}
          {cardSwipeAction === 'read' && <span>标为已读</span>}
          {cardSwipeAction === 'readLater' && <Clock aria-hidden className="size-4" />}
          {cardSwipeAction === 'readLater' && <span>稍后读</span>}
          {cardSwipeAction === 'star' && <Star aria-hidden className="size-4" />}
          {cardSwipeAction === 'star' && <span>收藏</span>}
        </div>
      )}

      {/* 内容层：translateX 跟手（未达阈值 touchend 归零 = 回弹） */}
      <div
        className="relative flex min-w-0 flex-1 items-start gap-2 px-4 py-3"
        style={
          swipeEnabled && swipeDx !== 0 ? { transform: `translateX(${swipeDx}px)` } : undefined
        }
      >
        {/* F07 多选复选框（真实 checkbox；44px 触控目标） */}
        {selectMode && (
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggleSelect?.(item.entryRef)}
            onClick={(event) => event.stopPropagation()}
            aria-label={`选择「${item.title}」`}
            className="mt-0.5 size-11 shrink-0 cursor-pointer accent-[var(--lumi-accent)]"
          />
        )}

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {/* 元信息行：状态点 + 来源（可点击）· 作者 · 时间 + 动作区。
              选中表面上 tertiary 对比度 4.43:1 不满足 WCAG AA → 用 secondary */}
          <div
            className={cx(
              'flex min-w-0 items-center gap-1.5 text-xs',
              selected
                ? 'text-[var(--lumi-text-secondary)]'
                : 'text-[var(--lumi-text-tertiary)]',
            )}
          >
            {/* 未读标记圆点是产品固定视觉语义（状态不只靠颜色） */}
            <span
              aria-hidden="true"
              className={cx(
                'size-1.5 shrink-0 rounded-full',
                item.read ? 'bg-transparent' : 'bg-[var(--lumi-accent)]',
              )}
            />
            <SourceGlyph name={item.feedTitle} />
            <SourceLabel
              feedTitle={item.feedTitle}
              feedUrl={item.feedUrl}
              className="min-w-0 max-w-[40%] font-medium text-left"
            />
            {item.author !== null && (
              <span className="hidden truncate lg:inline">· {item.author}</span>
            )}
            <span className="ml-auto shrink-0">{formatListTime(item.publishedAt, timeFormat)}</span>
            <EntryActionButtons entryRef={item.entryRef} starred={item.starred} compact />
          </div>

          {/* 标题：未读 medium/primary，已读 normal/secondary；桌面单行 truncate。 */}
          <button
            type="button"
            onClick={handleOpen}
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

          {/* F02 摘要（桌面一行截断；可关） */}
          {showSnippet && item.snippet !== null && item.snippet !== undefined && item.snippet !== '' && (
            <p className="truncate text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              {item.snippet}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default memo(EntryRow)
