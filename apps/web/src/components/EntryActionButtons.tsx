/** EntryActions — 文章行共享动作（0011 修正补充 §15–§20/§38）。
 *
 * 稍后读（Clock）+ 收藏（Star）两个图标按钮，供桌面 EntryRow 与移动
 * EntryCard 复用：共享 mutation/状态逻辑（useToggleReadLater +
 * useEntryStateMutation），布局由调用方决定（§38）。
 *
 * 语义（§39 统一认知）：
 *   ◷ Clock = 稍后读（之后还要看）  ☆ Star = 收藏（长期留下）
 *   三态独立：read / readLater / starred 互不覆盖（§28）。
 *
 * 可见性（§17/§18）：
 * - hover 设备（pointer:fine）：未激活动作默认弱显示（opacity-40），
 *   hover 行时增强——不隐藏不占位切换，日期/标题零跳动；
 * - touch（无可靠 hover）：始终完全可见（媒体查询降级）；
 * - 已激活（readLater/starred 为 true）始终完全可见（可扫描状态）。
 *
 * 布局约束：按钮不做 stopPropagation（调用方布局保证动作区与行点击
 * 不重叠）；触控目标 ≥44px（视觉 icon 18–20px，padding 补足 §20）。 */

import { Clock, Loader2, Star } from 'lucide-react'
import { useEntryStateMutation } from '../api/queries'
import { useToggleReadLater } from '../lib/read-later'
import { cx } from './ui/cx'

/** hover 增强（index.css 原生类 .entry-action-idle）：未激活时弱显示；
 * 行 hover / focus-within 时全显；触屏设备始终全显（无 hover 依赖）。
 * Tailwind v4 不支持 [@media..]:group-hover 叠加 variant，故用 CSS 类。 */
const idleCls = 'entry-action-idle'

export function EntryActionButtons({
  entryRef,
  starred,
  compact,
}: {
  entryRef: string
  starred: boolean
  /** 紧凑模式（桌面行）：按钮 28px、icon 16px；默认 44px 触控（卡片） */
  compact?: boolean
}) {
  const { isReadLater, toggleReadLater } = useToggleReadLater()
  const marked = isReadLater(entryRef)
  const mutation = useEntryStateMutation()

  const btnBase = compact
    ? 'flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] transition-[opacity,background-color,color] duration-[var(--lumi-motion-fast)]'
    : 'flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] transition-[opacity,background-color,color] duration-[var(--lumi-motion-fast)]'
  const iconSize = compact ? 'size-4' : 'size-5'
  const hoverCls =
    'hover:bg-[var(--lumi-surface-hover)] focus-visible:opacity-100 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'

  const starPending =
    mutation.isPending &&
    mutation.variables?.entryRef === entryRef &&
    'starred' in mutation.variables.patch

  return (
    <span className="flex shrink-0 items-center" data-entry-actions>
      {/* 稍后读：本地 marker（零网络），点击即时切换（§25 天然乐观） */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          toggleReadLater(entryRef)
        }}
        aria-pressed={marked}
        aria-label={marked ? '从稍后读移除' : '加入稍后读'}
        title={marked ? '从稍后读移除' : '加入稍后读'}
        className={cx(btnBase, hoverCls, !marked && idleCls)}
        style={marked ? { color: 'var(--lumi-accent)' } : { color: 'var(--lumi-text-tertiary)' }}
      >
        <Clock aria-hidden className={cx(iconSize, marked && 'fill-[var(--lumi-accent-soft)]')} />
      </button>

      {/* 收藏：set 语义 PATCH（乐观失败回滚由 0009 mutation 模式承载） */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (starPending) return
          mutation.mutate({ entryRef, patch: { starred: !starred } })
        }}
        aria-pressed={starred}
        aria-label={starred ? '取消收藏' : '收藏'}
        title={starred ? '取消收藏' : '收藏'}
        className={cx(btnBase, hoverCls, !starred && idleCls)}
        disabled={starPending}
        style={{ color: starred ? 'var(--lumi-category-orange)' : 'var(--lumi-text-tertiary)' }}
      >
        {starPending ? (
          <Loader2 aria-hidden className={cx(iconSize, 'animate-spin')} />
        ) : (
          <Star
            aria-hidden
            className={cx(
              iconSize,
              starred && 'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]',
            )}
          />
        )}
      </button>
    </span>
  )
}
