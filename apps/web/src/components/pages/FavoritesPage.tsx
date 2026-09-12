/** FavoritesPage — 收藏页（0011 Gate 3，参考图 02-favorites）。
 *
 * phase2 G6：联合收藏视图——RSS 星标仍走 view='starred' 服务端查询
 * （useEntries，FreshRSS 真值；不复制收藏数据到本地 store，Spec §5.1/AC5），
 * 库收藏走 GET /favorites 的 library 腿（展示层合并，两个域各自保有
 * 所有权，绝不跨域复制）；libraryError 小字诚实提示。
 *
 * 分组：RSS 收藏内再按 最近收藏（今天）/ 更早——排序来自真实
 * publishedAt 字段（API 本身按最新在前排序，分组只插入小节标题不重排）。
 *
 * 契约缺口诚实降级（Spec §7.5）：
 * - 搜索框/chips 只在语义真实时出现——当前无收藏内搜索契约 → 不渲染；
 * - 无「稍后读」独立状态 → 不伪造该分类 chip；
 * - 无批量清空 API → 不显示可用「清空」；
 * - 无摘要/缩略图 → EntryCard 文本退化。
 */

import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Star } from 'lucide-react'
import { useEntries, useFavorites } from '../../api/queries'
import type { EntryListItem } from '../../api/types'
import type { LibrarySearchItem } from '../../api/client'
import { useReaderUi, ALL_SCOPE } from '../../store/reader-ui'
import { resolveAndOpen } from '../../lib/open-item'
import { safeExternalHttpUrl } from '../../lib/safe-external-http-url'
import EntryCard from '../EntryCard'
import { LibraryFavoriteButton } from '../UnifiedContentCard'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

interface DateGroup {
  label: string
  items: EntryListItem[]
}

const LIBRARY_KIND_LABELS: Record<string, string> = {
  bookmark: '书签',
  clip: '剪藏',
  obsidian_note: '笔记',
  snapshot: '快照',
}

function libraryKindLabel(kind: string): string {
  return LIBRARY_KIND_LABELS[kind] ?? kind
}

/** 收藏分组：今天 →「最近收藏」；更早日期/无日期 →「更早」。
 * 纯展示层分组，保持 API 排序。 */
function groupFavorites(items: EntryListItem[], now = new Date()): DateGroup[] {
  const todayKey = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`
  const recent: EntryListItem[] = []
  const earlier: EntryListItem[] = []
  for (const item of items) {
    if (item.publishedAt === null) {
      earlier.push(item)
      continue
    }
    const d = item.publishedAt ? new Date(item.publishedAt) : new Date(NaN)
    if (Number.isNaN(d.getTime())) {
      earlier.push(item)
      continue
    }
    const key = `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
    ;(key === todayKey ? recent : earlier).push(item)
  }
  const groups: DateGroup[] = []
  if (recent.length > 0) groups.push({ label: '最近收藏', items: recent })
  if (earlier.length > 0) groups.push({ label: '更早', items: earlier })
  return groups
}

export default function FavoritesPage() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  // 复用 starred 服务端语义（feedUrl=null 全局收藏），不复制数据
  const starred = useEntries(ALL_SCOPE, 'starred')
  const { data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } = starred
  // phase2 G6：库收藏腿（展示层合并；失败/为空不影响 RSS 收藏展示）
  const favorites = useFavorites()
  const libraryItems = favorites.data?.library ?? []
  const libraryError = favorites.data?.libraryError ?? null

  const entries = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  )

  // 无限滚动（0011：与 EntryList 同一模式，替换「加载更多」按钮）
  const sentinelRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasNextPage || isFetchingNextPage) return
    const observer = new IntersectionObserver(
      (records) => {
        if (records.some((r) => r.isIntersecting) && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { rootMargin: '0px 0px 50% 0px' },
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, entries])

  if (isPending) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" aria-label="收藏加载中">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-4 w-4/5" />
          </div>
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
        <p>收藏加载失败</p>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{error.message}</p>
        <Button size="sm" onClick={() => refetch()} className="mt-2">
          重试
        </Button>
      </div>
    )
  }

  // 两腿都为空 → 空态（库腿失败/加载中不影响该判定：此刻库侧确无内容可展示；
  // libraryError 仍诚实附在空态下方）。
  if (entries.length === 0 && libraryItems.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <div>
          <EmptyState
            icon={<Star aria-hidden className="size-8" />}
            title="还没有收藏文章"
            description="阅读时点击「收藏」，文章会出现在这里。"
          />
          {libraryError !== null && (
            <p
              role="status"
              className="pb-6 text-center text-xs text-[var(--lumi-text-secondary)]"
            >
              库索引暂不可用：{libraryError}
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ul className="p-2">
          <li className="px-2 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
            RSS 收藏
          </li>
          {entries.length === 0 && (
            <li className="px-2 py-2 text-xs text-[var(--lumi-text-tertiary)]">还没有 RSS 收藏</li>
          )}
          {groupFavorites(entries).map((group) => (
            <Fragment key={group.label}>
              <li className="px-2 pb-1 pt-2.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                {group.label}
              </li>
              {group.items.map((item) => (
                <li key={item.entryRef} className="py-1">
                  <EntryCard item={item} selected={item.entryRef === selectedEntryRef} />
                </li>
              ))}
            </Fragment>
          ))}
          {/* 无限滚动哨兵（0011）：滚入视口自动拉下一页 */}
          {entries.length > 0 && (
            <li
              ref={sentinelRef}
              aria-hidden={hasNextPage || isFetchingNextPage ? undefined : 'true'}
              className="flex items-center justify-center py-4"
            >
              {isFetchingNextPage ? (
                <Loader2 aria-label="加载中" className="size-4 animate-spin text-[var(--lumi-text-tertiary)]" />
              ) : hasNextPage ? (
                <span className="text-xs text-[var(--lumi-text-tertiary)]">下滑加载更多…</span>
              ) : (
                <span className="text-xs text-[var(--lumi-text-tertiary)]">已经到底了</span>
              )}
            </li>
          )}
        </ul>

        {/* phase2 G6：库收藏（标题 / kind / url；libraryError 诚实小字） */}
        <section
          aria-label="库收藏"
          className="border-t border-[var(--lumi-separator)] px-2 pb-2 pt-2 max-lg:pb-[84px]"
        >
          <h3 className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
            库收藏
          </h3>
          {favorites.isPending && (
            <div className="flex flex-col gap-2 px-2 py-1" aria-label="库收藏加载中">
              <Skeleton className="h-10 w-full" />
            </div>
          )}
          {favorites.isError && (
            <p role="alert" className="px-2 py-1 text-xs text-[var(--lumi-danger)]">
              库收藏加载失败：{favorites.error.message}
            </p>
          )}
          {favorites.isSuccess && (
            <>
              {libraryError !== null && (
                <p role="status" className="px-2 py-1 text-xs text-[var(--lumi-text-secondary)]">
                  库索引暂不可用：{libraryError}
                </p>
              )}
              {libraryItems.length === 0 ? (
                <p className="px-2 py-1.5 text-xs text-[var(--lumi-text-tertiary)]">
                  还没有库收藏
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {libraryItems.map((item) => (
                    <LibraryRow key={item.ref} item={item} />
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}

/** 库收藏行：标题按钮（resolve → 按 kind 打开：Reader/外链/剪藏/快照/
 * Obsidian）+ kind 徽标 + 安全外链（http(s) 以外协议不放行）。
 * P0-10：行尾取消收藏（库域 removeLibraryFavorite；乐观移除 +
 * 失败回滚 + 错误原样透出）。RSS 收藏行为保持不变（FreshRSS star 真值）。
 * wave 2（P0-02/「一切皆可打开」）：stale 行禁用打开并注明原因，
 * 不再静默降级为纯文本。 */
function LibraryRow({ item }: { item: LibrarySearchItem }) {
  const safeUrl = safeExternalHttpUrl(item.url)
  const [openError, setOpenError] = useState<string | null>(null)
  const stale = item.stale

  const open = async () => {
    setOpenError(null)
    try {
      const resolved = await resolveAndOpen(item.ref)
      if (resolved === null) {
        setOpenError('打开失败：内容解析请求未成功，请稍后重试。')
      } else if (resolved.stale) {
        setOpenError('内容已失效，无法打开。')
      }
    } catch (error) {
      setOpenError(error instanceof Error ? error.message : '打开失败，请稍后重试。')
    }
  }

  return (
    <li
      className={cx(
        'flex flex-col gap-1 rounded-[var(--lumi-radius-lg)] px-2 py-2',
        'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
      )}
    >
      <span className="flex items-start gap-2">
        {stale ? (
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--lumi-text-secondary)]">
            {item.title}
          </span>
        ) : (
          <button
            type="button"
            onClick={() => void open()}
            className="min-w-0 flex-1 truncate text-left text-sm font-medium text-[var(--lumi-text-primary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            {item.title}
          </button>
        )}
        <LibraryFavoriteButton itemRef={item.ref} />
      </span>
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--lumi-text-tertiary)]">
        <span className="shrink-0 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-[11px]">
          {libraryKindLabel(item.kind)}
        </span>
        {stale && (
          <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            已失效
          </span>
        )}
        {safeUrl !== null && !stale && (
          <a
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="min-w-0 truncate text-[var(--lumi-accent-text)] hover:underline"
          >
            {safeUrl}
          </a>
        )}
      </span>
      {openError !== null && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          {openError}
        </span>
      )}
    </li>
  )
}
