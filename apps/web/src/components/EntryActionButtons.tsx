/** EntryActions — 文章行共享动作（0011 修正补充 §15–§20/§38）。
 *
 * 稍后读（Clock）+ 收藏（Star）+ 存书签（Bookmark）+ 添加到工作区
 * （FolderPlus 菜单）四个图标按钮，供桌面 EntryRow 与移动 EntryCard
 * 复用：共享 mutation/状态逻辑（useToggleReadLater +
 * useEntryStateMutation + useCreateBookmarkMutation +
 * useAddWorkspaceItemMutation），布局由调用方决定（§38）。
 *
 * 语义（§39 统一认知）：
 *   ◷ Clock = 稍后读（之后还要看）  ☆ Star = 收藏（长期留下）
 *   ⚑ Bookmark = 存书签（进入 library 书签库）  ▨ FolderPlus = 加入工作区
 *   四态独立：read / readLater / starred / bookmarked 互不覆盖。
 *
 * 可见性（§17/§18）：
 * - hover 设备（pointer:fine）：未激活动作默认弱显示（opacity-40），
 *   hover 行时增强——不隐藏不占位切换，日期/标题零跳动；
 * - touch（无可靠 hover）：始终完全可见（媒体查询降级）；
 * - 已激活（readLater/starred/bookmarked 为 true）始终完全可见。
 *
 * 布局约束：按钮不做 stopPropagation 之外的布局假设（调用方布局保证
 * 动作区与行点击不重叠；菜单面板走 portal，不会冒泡到行）；
 * 触控目标 ≥44px（视觉 icon 16–20px，padding 补足 §20）。
 *
 * 存书签激活态：v1 以 ['library','bookmarks','rss-refs']（首页
 * rssItemRef 集合）为依据；POST 幂等（重复存返回同一 ref）。标题
 * 未显式传入时从 query cache（entry detail / entries / search 列表）
 * 解析——行正在渲染，标题必然在缓存中。 */

import { useMemo, useState } from 'react'
import { Bookmark, Check, Clock, FolderPlus, Loader2, Star } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import {
  useAddWorkspaceItemMutation,
  useBookmarkRssRefs,
  useCreateBookmarkMutation,
  useEntryStateMutation,
  useWorkspaces,
} from '../api/queries'
import type { EntryDetail, EntryListItem } from '../api/types'
import { useToggleReadLater } from '../lib/read-later'
import { IconButton } from './ui/IconButton'
import { Menu } from './ui/Menu'
import { cx } from './ui/cx'

/** hover 增强（index.css 原生类 .entry-action-idle）：未激活时弱显示；
 * 行 hover / focus-within 时全显；触屏设备始终全显（无 hover 依赖）。
 * Tailwind v4 不支持 [@media..]:group-hover 叠加 variant，故用 CSS 类。 */
const idleCls = 'entry-action-idle'

/** 存书签标题解析：显式 prop → entry detail 缓存 → 列表缓存扫描 →
 * 兜底（BFF 要求 title 非空，绝不发空标题）。 */
function resolveEntryTitle(
  entryRef: string,
  explicitTitle: string | undefined,
  detail: EntryDetail | undefined,
  lists: { pages: { items: EntryListItem[] }[] }[],
): string {
  if (explicitTitle !== undefined && explicitTitle.trim() !== '') {
    return explicitTitle.trim()
  }
  if (detail?.title !== undefined && detail.title.trim() !== '') {
    return detail.title.trim()
  }
  for (const data of lists) {
    for (const page of data?.pages ?? []) {
      const hit = page.items.find((it) => it.entryRef === entryRef)
      if (hit?.title !== undefined && hit.title.trim() !== '') {
        return hit.title.trim()
      }
    }
  }
  return '未命名文章'
}

export function EntryActionButtons({
  entryRef,
  starred,
  title,
  compact,
}: {
  entryRef: string
  starred: boolean
  /** 文章标题（存书签用）；缺省时从 query cache 解析 */
  title?: string
  /** 紧凑模式（桌面行）：按钮 28px、icon 16px；默认 44px 触控（卡片） */
  compact?: boolean
}) {
  const { isReadLater, toggleReadLater } = useToggleReadLater()
  const marked = isReadLater(entryRef)
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()

  // ---- 存书签（library 域，POST 幂等） ----
  const createBookmark = useCreateBookmarkMutation()
  const bookmarkRefs = useBookmarkRssRefs()
  const bookmarkedRssRefs = useMemo(
    () =>
      new Set(
        (bookmarkRefs.data?.items ?? [])
          .map((b) => b.rssItemRef ?? '')
          .filter((ref) => ref !== ''),
      ),
    [bookmarkRefs.data],
  )
  const bookmarked = bookmarkedRssRefs.has(`rss:${entryRef}`)
  const bookmarkPending =
    createBookmark.isPending && createBookmark.variables?.rssItemRef === `rss:${entryRef}`

  const saveBookmark = () => {
    if (bookmarkPending) return
    const lists = [
      ...queryClient.getQueriesData<{ pages: { items: EntryListItem[] }[] }>({
        queryKey: ['entries'],
      }).map(([, d]) => d),
      ...queryClient.getQueriesData<{ pages: { items: EntryListItem[] }[] }>({
        queryKey: ['search'],
      }).map(([, d]) => d),
    ].filter((d): d is { pages: { items: EntryListItem[] }[] } => d !== undefined)
    createBookmark.mutate({
      rssItemRef: `rss:${entryRef}`,
      title: resolveEntryTitle(
        entryRef,
        title,
        queryClient.getQueryData<EntryDetail>(['entry', entryRef]),
        lists,
      ),
    })
  }

  // ---- 添加到工作区（Menu；POST 幂等） ----
  const workspaces = useWorkspaces()
  const addItem = useAddWorkspaceItemMutation()
  // v1 会话内成功反馈：加入过的工作区在菜单里打勾（POST 幂等，可重加）。
  const [addedWorkspaceIds, setAddedWorkspaceIds] = useState<Set<string>>(new Set())
  const addPending =
    addItem.isPending && addItem.variables?.itemRef === `rss:${entryRef}`

  const addToWorkspace = (workspaceId: string) => {
    addItem.mutate(
      { workspaceId, itemRef: `rss:${entryRef}` },
      {
        onSuccess: () =>
          setAddedWorkspaceIds((prev) => new Set(prev).add(workspaceId)),
      },
    )
  }

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

      {/* 存书签：POST 幂等（重复存同一 rssItemRef 返回同一 ref）。
          激活态 = rss-refs 集合命中；错误时按钮 title 承载原因（可重试）。 */}
      <IconButton
        icon={
          bookmarkPending ? (
            <Loader2 aria-hidden className={iconSize} />
          ) : (
            <Bookmark
              aria-hidden
              className={cx(iconSize, bookmarked && 'fill-[var(--lumi-accent)]')}
            />
          )
        }
        label="存书签"
        aria-pressed={bookmarked}
        title={
          bookmarkPending
            ? '存书签中…'
            : createBookmark.isError && createBookmark.variables?.rssItemRef === `rss:${entryRef}`
              ? `存书签失败：${createBookmark.error instanceof Error ? createBookmark.error.message : '请稍后重试'}`
              : bookmarked
                ? '已存书签'
                : '存书签'
        }
        size={compact ? 'sm' : 'md'}
        touch={!compact}
        className={cx(!bookmarked && idleCls)}
        style={{ color: bookmarked ? 'var(--lumi-accent)' : 'var(--lumi-text-tertiary)' }}
        disabled={bookmarkPending}
        onClick={(e) => {
          e.stopPropagation()
          saveBookmark()
        }}
      />

      {/* 添加到工作区：溢出菜单（Base UI 行为底座），列出全部工作区
          （稍后读保留工作区也在列，POST 幂等）；会话内加入过的条目打勾。 */}
      <Menu
        trigger={({ triggerProps }) => (
          <IconButton
            icon={<FolderPlus aria-hidden className={iconSize} />}
            label="添加到工作区"
            title={addedWorkspaceIds.size > 0 ? '已加入（可继续添加到其它工作区）' : '添加到工作区'}
            size={compact ? 'sm' : 'md'}
            touch={!compact}
            className={idleCls}
            style={{ color: 'var(--lumi-text-tertiary)' }}
            disabled={addPending}
            {...triggerProps}
            onClick={(e) => {
              e.stopPropagation()
              triggerProps.onClick?.(e)
            }}
          />
        )}
        items={
          workspaces.isPending
            ? [{ key: '__loading', content: '加载中…', disabled: true }]
            : (workspaces.data?.items ?? []).map((w) => ({
                key: w.id,
                content: (
                  <>
                    <span className="min-w-0 flex-1 truncate">
                      {w.reserved ? '稍后读' : w.name}
                    </span>
                    {addedWorkspaceIds.has(w.id) && (
                      <Check
                        aria-hidden
                        className="size-4 shrink-0 text-[var(--lumi-accent-text)]"
                      />
                    )}
                  </>
                ),
              }))
        }
        onSelect={addToWorkspace}
      />
    </span>
  )
}
