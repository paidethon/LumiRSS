/** UnifiedContentCard — 统一内容卡片（phase2 M1 Library 域）。
 *
 * RSS 条目与库书签的统一展示（ResolvedItem 由 BFF /workspaces/{id}/contents
 * 解析而来）：标题 + 域徽标（RSS / 库 / 未知）+ 诚实来源行 + 摘要
 * （plain text，2 行截断，绝不 innerHTML）+ 外链（仅绝对 http/https，
 * 经 safeExternalHttpUrl 边界）。
 *
 * stale（源已失效）：无链接、徽标降为 muted——不伪造可打开的内容；
 * 上层（工作区页）会给出「建议移除」提示。
 *
 * 纯展示组件：动作区（actions）与打开行为（onOpen）由调用方注入，
 * 本组件不包含任何数据获取。 */

import type { ReactNode } from 'react'
import type { ResolvedItem } from '../api/types'
import { formatPublishedAt } from '../lib/date-format'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { cx } from './ui/cx'

/** kind → 徽标文案（RSS 条目 / 库书签 / 未知引用，诚实标注）。 */
function kindLabel(kind: string): string {
  if (kind === 'rss') return 'RSS'
  if (kind === 'bookmark') return '库'
  return '未知'
}

export function UnifiedContentCard({
  item,
  actions,
  onOpen,
}: {
  item: ResolvedItem
  /** 卡片动作区（移除 / 上移 / 下移等），布局由本组件承载 */
  actions?: ReactNode
  /** 打开内容（v1 工作区页的 rss 条目不接 Reader，仅外链）；stale 时无效 */
  onOpen?: () => void
}) {
  const stale = item.stale
  // 外链安全边界：只放行绝对 http/https；stale 一律不给链接。
  const safeUrl = stale ? null : safeExternalHttpUrl(item.url ?? null)
  const canOpen = onOpen !== undefined && !stale

  return (
    <article
      data-domain={item.domain}
      data-stale={stale || undefined}
      className={cx(
        'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5',
        stale && 'opacity-80',
      )}
    >
      <div className="flex items-start gap-2">
        <h3 className="min-w-0 flex-1 text-sm font-medium text-[var(--lumi-text-primary)]">
          {canOpen ? (
            <button
              type="button"
              onClick={onOpen}
              className="w-full text-left transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              {item.title}
            </button>
          ) : (
            <span className={cx('line-clamp-2', stale && 'text-[var(--lumi-text-secondary)]')}>
              {item.title}
            </span>
          )}
        </h3>
        {/* 域徽标：纯文本（无图标），stale 时降为 muted「源已失效」 */}
        <span
          className={cx(
            'shrink-0 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px] font-medium',
            stale
              ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]'
              : 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]',
          )}
        >
          {stale ? '源已失效' : kindLabel(item.kind)}
        </span>
      </div>

      {/* 诚实来源行：真实 source + 解析时间（缺失显示 —） */}
      <p className="mt-1 flex min-w-0 items-center gap-1 text-xs text-[var(--lumi-text-tertiary)]">
        {item.source !== '' && <span className="truncate">{item.source}</span>}
        <span aria-hidden>·</span>
        <span className="shrink-0">{formatPublishedAt(item.datetime ?? null)}</span>
      </p>

      {item.excerpt != null && item.excerpt !== '' && (
        <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {item.excerpt}
        </p>
      )}

      {safeUrl !== null && (
        <a
          href={safeUrl}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1.5 block truncate text-xs text-[var(--lumi-accent-text)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          {safeUrl}
        </a>
      )}

      {actions !== undefined && (
        <div className="mt-2.5 flex min-h-7 items-center gap-1.5">{actions}</div>
      )}
    </article>
  )
}

export default UnifiedContentCard
