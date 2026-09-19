/** EntryActions — 文章行共享动作（0011 修正补充 §15–§20/§38）。
 *
 * 稍后读（Clock）+ 收藏（Star）+ 存书签（Bookmark）+ 添加到工作区
 * （FolderPlus 菜单）+ 标签（Tags 弹出面板，P0-10）五个动作，供桌面
 * EntryRow 与移动 EntryCard 复用：共享 mutation/状态逻辑（useToggleReadLater +
 * useEntryStateMutation + useCreateBookmarkMutation +
 * useAddWorkspaceItemMutation + assign/unassignTag），布局由调用方决定（§38）。
 *
 * 语义（§39 统一认知）：
 *   ◷ Clock = 稍后读（之后还要看）  ☆ Star = 收藏（长期留下）
 *   ⚑ Bookmark = 存书签（进入 library 书签库）  ▨ FolderPlus = 加入工作区
 *   # Tags = 标签管理（绑定/解绑/新建，P0-10 首批 UI 消费者）
 *   五态独立：read / readLater / starred / bookmarked / tags 互不覆盖。
 *
 * 可见性（§17/§18）：
 * - hover 设备（pointer:fine）：未激活动作默认弱显示（opacity-40），
 *   hover 行时增强——不隐藏不占位切换，日期/标题零跳动；
 * - touch（无可靠 hover）：始终完全可见（媒体查询降级）；
 * - 已激活（readLater/starred/bookmarked/有标签）始终完全可见。
 *
 * 布局约束：按钮不做 stopPropagation 之外的布局假设（调用方布局保证
 * 动作区与行点击不重叠；菜单/弹出面板走 portal，不会冒泡到行）；
 * 触控目标 ≥44px（视觉 icon 16–20px，padding 补足 §20）。
 *
 * 存书签激活态：v1 以 ['library','bookmarks','rss-refs']（首页
 * rssItemRef 集合）为依据；POST 幂等（重复存返回同一 ref）。标题
 * 未显式传入时从 query cache（entry detail / entries / search 列表）
 * 解析——行正在渲染，标题必然在缓存中。
 *
 * P0-10 标签面板契约：ItemRef 统一格式 `rss:<entryRef>`；勾选状态以
 * GET /tags/item（status='attached'）为真值；suggested 行如实标注
 * 「建议」，只有显式勾选才绑定。时间线的标签过滤需要服务端契约
 * （wave 2），不在本组件。 */

import { useMemo, useState } from 'react'
import {
  Bookmark,
  CalendarClock,
  Check,
  Clock,
  FolderPlus,
  Languages,
  Loader2,
  Star,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import {
  SEARCH_RESULTS_KEY,
  useAddWorkspaceItemMutation,
  useBookmarkRssRefs,
  useCreateBookmarkMutation,
  useEntryStateMutation,
  useItemTags,
  useTitleTranslationMutation,
  useSnoozeReadLaterMutation,
  useWorkspaces,
} from '../api/queries'
import { getEntry } from '../api/client'
import { useUndo } from '../store/undo'
import type { EntryDetail, EntryListItem } from '../api/types'
import { useToggleReadLater } from '../lib/read-later'
import { ItemTagButton } from './ItemTagButton'
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
  const { isReadLater, toggleReadLater, pendingFor, errorFor } = useToggleReadLater()
  const marked = isReadLater(entryRef)
  const readLaterPending = pendingFor(entryRef)
  const readLaterError = errorFor(entryRef)
  const mutation = useEntryStateMutation()
  const queryClient = useQueryClient()
  // F20：收藏动作的短时撤销（8 秒；撤销前核对服务器状态，防跨设备覆盖）
  const pushUndo = useUndo((s) => s.push)
  // F23：按需标题翻译（缓存优先，一次一条）
  const titleTranslation = useTitleTranslationMutation()

  const starUndo = (next: boolean) => {
    pushUndo({
      label: next ? '已收藏' : '已取消收藏',
      check: async () => {
        const detail = await queryClient.fetchQuery({
          queryKey: ['entry', entryRef],
          queryFn: ({ signal }) => getEntry(entryRef, signal),
          staleTime: 0,
        })
        return detail.starred === next
      },
      undo: async () => {
        await mutation.mutateAsync({ entryRef, patch: { starred: !next } })
      },
    })
  }

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
        queryKey: SEARCH_RESULTS_KEY,
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

  // P0-10：条目的既有标签（勾选/激活态）。
  const itemTags = useItemTags(`rss:${entryRef}`)
  const attachedTagNames = useMemo(
    () =>
      new Set(
        (itemTags.data?.items ?? [])
          .filter((t) => t.status === 'attached')
          .map((t) => t.name),
      ),
    [itemTags.data],
  )

  return (
    <span className="flex shrink-0 items-center" data-entry-actions>
      {/* 稍后读：服务端保留工作区成员（P0-01）——乐观切换 + 失败回滚
          由 useReadLaterMemberMutation 承载；错误行内诚实透出。 */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (readLaterPending) return
          toggleReadLater(entryRef)
        }}
        aria-pressed={marked}
        aria-label={marked ? '从稍后读移除' : '加入稍后读'}
        title={marked ? '从稍后读移除' : '加入稍后读'}
        className={cx(btnBase, hoverCls, !marked && idleCls)}
        disabled={readLaterPending}
        style={{ color: marked ? 'var(--lumi-accent)' : 'var(--lumi-text-tertiary)' }}
      >
        {readLaterPending ? (
          <Loader2 aria-hidden className={cx(iconSize, 'animate-spin')} />
        ) : (
          <Clock aria-hidden className={cx(iconSize, marked && 'fill-[var(--lumi-accent-soft)]')} />
        )}
      </button>

      {/* F19 延后：仅对已在稍后读的条目提供——把项目推迟 7 天，到期自动
          回到时间线；行保留、已读/收藏状态不受影响。 */}
      {marked ? (
        <SnoozeButton entryRef={entryRef} itemRef={`rss:${entryRef}`} btnBase={btnBase} hoverCls={hoverCls} iconSize={iconSize} idleCls={idleCls} />
      ) : null}

      {/* 收藏：set 语义 PATCH（乐观失败回滚由 0009 mutation 模式承载）；
          F20：成功后提供 8 秒撤销窗口（核对服务器状态后逆操作）。 */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          if (starPending) return
          const next = !starred
          mutation.mutate({ entryRef, patch: { starred: next } }, {
            onSuccess: () => starUndo(next),
          })
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

      {/* P0-10：标签（Base UI Popover：勾选既有标签 + 新建 + 绑定/解绑）。
          面板走 portal，不冒泡到行。Q-P1-09：提取为 kind 无关的
          ItemTagButton（UnifiedContentCard 库类条目同用）。 */}
      <ItemTagButton
        itemRef={`rss:${entryRef}`}
        compact={compact}
        idleCls={idleCls}
        attachedCount={attachedTagNames.size}
      />

      {/* F23：按需翻译标题（单条显式动作，不批量）。译文以 muted 副行
          叠加在原题下方（由调用方布局承接 titleTranslation 状态）。 */}
      <IconButton
        icon={
          titleTranslation.isPending &&
          titleTranslation.variables?.entryRef === entryRef ? (
            <Loader2 aria-hidden className={cx(iconSize, 'animate-spin')} />
          ) : (
            <Languages aria-hidden className={iconSize} />
          )
        }
        label="翻译标题"
        title={
          titleTranslation.data && titleTranslation.variables?.entryRef === `rss:${entryRef}` && false
            ? '再次点击刷新译文'
            : '翻译标题（原题保留）'
        }
        size={compact ? 'sm' : 'md'}
        touch={!compact}
        className={idleCls}
        style={{ color: 'var(--lumi-text-tertiary)' }}
        disabled={titleTranslation.isPending}
        onClick={(e) => {
          e.stopPropagation()
          titleTranslation.mutate({ entryRef: `rss:${entryRef}` })
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
      {/* P0-01：稍后读写失败（加入/移除）诚实透出——不吞不假装成功。
          紧凑模式靠 title 提示 + role=alert 播报，不撑破行布局。 */}
      {readLaterError !== null && (
        <span
          role="alert"
          title={`稍后读操作失败：${readLaterError instanceof Error ? readLaterError.message : '请稍后重试。'}`}
          aria-label={`稍后读操作失败：${readLaterError instanceof Error ? readLaterError.message : '请稍后重试。'}`}
          className={cx(
            'shrink-0 rounded-full bg-[var(--lumi-danger)]',
            compact ? 'size-1.5' : 'size-2',
          )}
        />
      )}
    </span>
  )
}

/** F19 延后按钮（Clock 旁；仅稍后读条目显示）。
 *
 * 单击 = 延后 7 天（最常用的「以后再看」语义，不弹菜单）；Shift+单击 =
 * 延后 1 天。成功后时间线失效，行从列表消失（到期自动回来）——
 * 这是有意的可见性变化，不是删除。 */
function SnoozeButton({
  itemRef,
  btnBase,
  hoverCls,
  iconSize,
  idleCls,
}: {
  entryRef: string
  itemRef: string
  btnBase: string
  hoverCls: string
  iconSize: string
  idleCls: string
}) {
  const snooze = useSnoozeReadLaterMutation()
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        snooze.mutate({ itemRef, days: e.shiftKey ? 1 : 7 })
      }}
      aria-label="延后该条目（默认 7 天）"
      title="延后 7 天（Shift+点击 = 1 天），到期自动回到稍后读"
      className={cx(btnBase, hoverCls, idleCls)}
    >
      {snooze.isPending && snooze.variables?.itemRef === itemRef ? (
        <Loader2 aria-hidden className={cx(iconSize, 'animate-spin')} />
      ) : (
        <CalendarClock aria-hidden className={iconSize} />
      )}
    </button>
  )
}
