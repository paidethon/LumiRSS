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
import { EntryActionButtons } from './EntryActionButtons'
import { cx } from './ui/cx'
import { formatListTime } from '../lib/date-format'
import { SourceGlyph, SourceLabel } from '../lib/source-meta'

/** EntryCard — 移动端共享卡片（0011 Gate 3；2026-09 移动端专项重构）。
 *
 * 层级（P2 统一元信息 + F01–F04 列表展示）：
 *
 *   [☑] [●] [A] 来源（可点击进该来源）   时间   [◷ 稍后读 ★ 收藏]
 *       标题（未读 medium；已读 normal，最多 3 行）      [封面(F03)]
 *       摘要两行截断（F02，可关；无摘要字段时该行不渲染）
 *
 * - 来源缺失降级「来源未知」（绝不 undefined/空分隔点）；无 feedUrl
 *   时是纯文本，不伪装可点击按钮；
 * - 密度（F01）由列表容器 data-density 驱动（index.css），不缩小触控区；
 * - 封面（F03）仅 listShowCover 时渲染（关闭 = 不请求）；onError 隐藏
 *   但保留占位，无图布局稳定；
 * - 时间（F04）相对/绝对由设置驱动；
 * - F07 多选：selectMode=true 时左侧出现 44px 复选框，点行 = 切换选中
 *   （不打开文章）；
 * - F08 滑动：cardSwipeAction !== 'none' 时内容层 translateX 跟手
 *   （0.4 倍、上限 100px），背景层显示动作图标；touchend 达 80px 阈值
 *   执行动作后回位，未达回弹；起点在屏幕左缘 24px 内不处理（让给
 *   侧滑返回）；
 * - F10：打开文章时记录最近阅读（开关关闭时 lib 内部 no-op）。
 *
 * memo 边界：props 仅稳定引用的 item + 布尔 selected + 多选回调
 * （调用方用 useCallback 保持稳定）。 */
function EntryCard({
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
  const showCover = useAppSettings((s) => s.settings.listShowCover)
  const timeFormat = useAppSettings((s) => s.settings.listTimeFormat)
  const cardSwipeAction = useAppSettings((s) => s.settings.cardSwipeAction)
  const { mutate: mutateEntryState } = useEntryStateMutation()
  const { toggleReadLater } = useToggleReadLater()

  // ---- F08 滑动手势（跟手预览 + 阈值提交；动作执行走既有 mutation） ----
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
    // 纵向让出：滚动意图下不做水平预览
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
    // 提交成功时吞掉合成的 click，避免动作 + 打开文章双重触发
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
        'lumi-entry-card group/row relative flex w-full overflow-hidden rounded-[var(--lumi-radius-lg)] text-left',
        'transition-colors duration-[var(--lumi-motion-fast)]',
        dimRead && item.read && 'opacity-60',
        selected
          ? 'bg-[var(--lumi-surface-selected)]'
          : 'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
      )}
    >
      {/* F08 动作背景层：跟手预览时在滑动侧显示动作图标（不拦截指针） */}
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
        className="relative flex min-w-0 flex-1 items-start gap-2 px-3.5 py-3"
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

        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          {/* 元信息行：状态点 + 来源（可点击）+ 时间 + 动作区（触屏常显）。
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
            {/* 来源按钮 min-w-0：动作区固定占位，来源保留可识别片段 */}
            <SourceLabel
              feedTitle={item.feedTitle}
              feedUrl={item.feedUrl}
              className="min-w-0 flex-1 font-medium text-left"
            />
            <span className="shrink-0">{formatListTime(item.publishedAt, timeFormat)}</span>
            <EntryActionButtons entryRef={item.entryRef} starred={item.starred} />
          </div>

          {/* 内容行：标题（打开 Reader）+ 封面缩略图（F03，可选） */}
          <div className="flex items-start gap-3">
            <button
              type="button"
              onClick={handleOpen}
              aria-pressed={selected}
              className={cx(
                'min-w-0 flex-1 rounded-[var(--lumi-radius-md)] text-left text-[15px] leading-snug line-clamp-3',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                item.read
                  ? 'font-normal text-[var(--lumi-text-secondary)]'
                  : 'font-medium text-[var(--lumi-text-primary)]',
              )}
            >
              {item.title}
            </button>
            {showCover && item.coverUrl !== null && item.coverUrl !== undefined && (
              <EntryCover src={item.coverUrl} />
            )}
          </div>

          {/* F02 摘要：来自 BFF 列表级 enrich（≤160 字纯文本），可关 */}
          {showSnippet && item.snippet !== null && item.snippet !== undefined && item.snippet !== '' && (
            <p className="line-clamp-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              {item.snippet}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

/** F03 封面缩略图：固定尺寸占位（无图/失败布局稳定）；仅渲染时才请求。
 * 装饰性（aria-hidden）——标题已承载语义；referrerPolicy=no-referrer。 */
const EntryCover = memo(function EntryCover({ src }: { src: string }) {
  return (
    <span
      aria-hidden="true"
      className="relative block h-16 w-24 shrink-0 overflow-hidden rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)]"
    >
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        className="size-full object-cover"
        onError={(event) => {
          event.currentTarget.style.display = 'none'
        }}
      />
    </span>
  )
})

export default memo(EntryCard)
