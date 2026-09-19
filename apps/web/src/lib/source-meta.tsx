/** P2（2026-09 移动端专项）：统一来源元信息。
 *
 * 全部文章卡片/列表行/搜索结果/阅读页共用同一套来源语义：
 * - 名称缺失/空白 → 「来源未知」（绝不渲染 undefined/空串/裸分隔点）；
 * - 中性图标：无上游 favicon 数据（且不把私人订阅发给第三方 favicon
 *   服务），用来源名首字符的圆角方块做稳定占位（浅/深色都清晰）；
 * - 可点击来源 = 有真实 feedUrl 时进入该订阅范围；没有目标时只渲染
 *   文本，不伪造可点击按钮。
 */

import { memo } from 'react'
import { useReaderUi } from '../store/reader-ui'
import { cx } from '../components/ui/cx'

/** 来源显示名：空白/undefined → 「来源未知」。 */
export function resolveSourceName(name: string | null | undefined): string {
  const trimmed = name?.trim()
  return trimmed ? trimmed : '来源未知'
}

/** 首字符（用于中性来源图标；中文取第一个字，英文取首字母大写）。 */
function sourceGlyphChar(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '·'
  const first = [...trimmed][0] ?? '·'
  return /[a-z]/.test(first) ? first.toUpperCase() : first
}

/** 中性来源图标（非 favicon 抓取：零网络、零隐私外发）。 */
export const SourceGlyph = memo(function SourceGlyph({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      data-source-glyph=""
      className="flex size-4 shrink-0 select-none items-center justify-center rounded-[5px] bg-[var(--lumi-surface-hover)] text-[9px] font-semibold leading-none text-[var(--lumi-text-secondary)]"
    >
      {sourceGlyphChar(name)}
    </span>
  )
})

/** 来源导航：有真实 feedUrl 才可点击进入该订阅范围（home section）。 */
export function useGoToFeed() {
  const selectScope = useReaderUi((s) => s.selectScope)
  const selectSection = useReaderUi((s) => s.selectSection)
  return (feedUrl: string | null | undefined) => {
    if (feedUrl === null || feedUrl === undefined || feedUrl === '') return
    selectSection('home')
    selectScope({ kind: 'rss-feed', feedUrl })
  }
}

/** 来源按钮/文本：feedUrl 存在 → button（进入该来源）；否则纯文本。
 *  不可点击绝不伪装按钮（无 href/role/cursor）。 */
export function SourceLabel({
  feedTitle,
  feedUrl,
  className,
  interactiveClassName,
}: {
  feedTitle: string | null | undefined
  feedUrl?: string | null
  className?: string
  interactiveClassName?: string
}) {
  const name = resolveSourceName(feedTitle)
  const goToFeed = useGoToFeed()
  const clickable = feedUrl !== null && feedUrl !== undefined && feedUrl !== ''
  if (!clickable) {
    return <span className={cx('truncate', className)}>{name}</span>
  }
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation()
        goToFeed(feedUrl)
      }}
      title={`只看来自「${name}」的文章`}
      className={cx(
        'truncate rounded-[var(--lumi-radius-sm)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
        className,
        interactiveClassName,
      )}
    >
      {name}
    </button>
  )
}
