/** FavoritesPage — 收藏页（0011 Gate 3，参考图 02-favorites）。
 *
 * 复用 view='starred' 服务端查询（useEntries）——不复制收藏数据到
 * 本地 store（Spec §5.1/AC5）；取消星标后由 useEntryStateMutation 的
 * 前缀 invalidate 保证列表与缓存一致（0009 既有机制）。
 *
 * 分组：最近收藏（今天） / 更早——排序来自真实 publishedAt 字段
 * （API 本身按最新在前排序，分组只插入小节标题不重排）。
 *
 * 契约缺口诚实降级（Spec §7.5）：
 * - 搜索框/chips 只在语义真实时出现——当前无收藏内搜索契约 → 不渲染；
 * - 无「稍后读」独立状态 → 不伪造该分类 chip；
 * - 无批量清空 API → 不显示可用「清空」；
 * - 无摘要/缩略图 → EntryCard 文本退化。
 */

import { Fragment, useEffect, useMemo, useRef } from 'react'
import { Loader2, Star } from 'lucide-react'
import { useEntries } from '../../api/queries'
import type { EntryListItem } from '../../api/types'
import { useReaderUi, ALL_SCOPE } from '../../store/reader-ui'
import EntryCard from '../EntryCard'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

interface DateGroup {
  label: string
  items: EntryListItem[]
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
    const d = new Date(item.publishedAt)
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

  if (entries.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <EmptyState
          icon={<Star aria-hidden className="size-8" />}
          title="还没有收藏文章"
          description="阅读时点击「收藏」，文章会出现在这里。"
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ul className="p-2">
          {groupFavorites(entries).map((group) => (
            <Fragment key={group.label}>
              <li className="px-2 pb-1 pt-2.5 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
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
          <li
            ref={sentinelRef}
            aria-hidden={hasNextPage || isFetchingNextPage ? undefined : 'true'}
            className="flex items-center justify-center py-4 max-md:pb-[84px]"
          >
            {isFetchingNextPage ? (
              <Loader2 aria-label="加载中" className="size-4 animate-spin text-[var(--lumi-text-tertiary)]" />
            ) : hasNextPage ? (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">下滑加载更多…</span>
            ) : (
              <span className="text-xs text-[var(--lumi-text-tertiary)]">已经到底了</span>
            )}
          </li>
        </ul>
      </div>
    </div>
  )
}
