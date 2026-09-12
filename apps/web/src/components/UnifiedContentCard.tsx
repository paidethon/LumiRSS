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
 * P0-10：库类条目（bookmark/clip/snapshot/obsidian_note）内联收藏切换
 * （addLibraryFavorite/removeLibraryFavorite 首批 UI 消费者；乐观更新 +
 * 失败回滚由 useLibraryFavoriteMutation 承载，错误原样透出）。RSS 条目
 * 不显示（收藏语义归 RSS star，绝不跨域复制）。
 *
 * 其余动作（actions）与打开行为（onOpen）仍由调用方注入。 */

import { Star, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ResolvedItem } from '../api/types'
import { useLibraryFavoriteToggle } from '../api/queries'
import { formatPublishedAt } from '../lib/date-format'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

/** kind → 徽标文案（RSS 条目 / 库书签 / 未知引用，诚实标注）。 */
function kindLabel(kind: string): string {
  if (kind === 'rss') return 'RSS'
  if (kind === 'bookmark') return '库'
  return '未知'
}

/** P0-10：库类条目收藏切换可用的 kind 集合（与 BFF library 域一致）。 */
const LIBRARY_FAVORITE_KINDS = new Set(['bookmark', 'clip', 'snapshot', 'obsidian_note'])

/** 库收藏切换按钮（乐观更新 + 失败回滚在 mutation hook；此处诚实透出
 * pending 与错误，不假装成功）。 */
export function LibraryFavoriteButton({ itemRef }: { itemRef: string }) {
  const { favorite, pending, error, toggle } = useLibraryFavoriteToggle(itemRef)
  return (
    <span className="flex items-center gap-1.5">
      <IconButton
        icon={
          pending ? (
            <Loader2 aria-hidden className="size-4 animate-spin" />
          ) : (
            <Star
              aria-hidden
              className={cx('size-4', favorite && 'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]')}
            />
          )
        }
        label={favorite ? '取消收藏' : '加入收藏'}
        title={favorite ? '取消收藏' : '加入收藏'}
        aria-pressed={favorite}
        size="sm"
        touch
        disabled={pending}
        onClick={toggle}
      />
      {error !== null && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          收藏操作失败：{error instanceof Error ? error.message : '请稍后重试。'}
        </span>
      )}
    </span>
  )
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

      {/* P0-10：库类条目的收藏切换 + 调用方动作区同一行（库类才显示）。 */}
      {(actions !== undefined || LIBRARY_FAVORITE_KINDS.has(item.kind)) && (
        <div className="mt-2.5 flex min-h-7 items-center gap-1.5">
          {LIBRARY_FAVORITE_KINDS.has(item.kind) && (
            <LibraryFavoriteButton itemRef={item.ref} />
          )}
          {actions}
        </div>
      )}
    </article>
  )
}

export default UnifiedContentCard
