/** ContinueReadingCard — F056 侧栏「继续阅读」卡片（桌面）。
 *
 * 消费 GET /api/v1/reading-progress（最近 5 条：标题+更新时间+设备名）；
 * 点击打开文章并定位段落（复用 F015 定位：reader?entry=&para= 语义，
 * 本地通过 reader-ui selectEntry + 段落参数挂到 hash 供 Reader 消费）；
 * 文章删除（进度残留）→ 列表项标「已失效」可忽略/移除，诚实处理。
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ListRestart } from 'lucide-react'
import { listReadingProgress } from '../api/client'
import { useReaderUi } from '../store/reader-ui'

export default function ContinueReadingCard() {
  const query = useQuery({
    queryKey: ['reading-progress'],
    queryFn: () => listReadingProgress(5),
    staleTime: 15_000,
  })
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const queryClient = useQueryClient()
  if (query.isPending || query.isError) return null
  const items = query.data?.items ?? []
  if (items.length === 0) return null
  return (
    <div className="mt-1 flex flex-col gap-0.5 px-1" aria-label="继续阅读">
      <p className="flex items-center gap-1.5 px-1.5 pt-1 text-[11px] font-medium uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        <ListRestart aria-hidden className="size-3.5" />
        继续阅读
      </p>
      {items.map((item) => (
        <button
          key={item.entryRef}
          type="button"
          onClick={async () => {
            selectEntry(item.entryRef)
            if (item.paraId !== '') {
              // F015 段落定位：Reader 打开后按 data-para-id 滚动
              sessionStorage.setItem('lumi-resume-para', item.paraId)
            }
            await queryClient.invalidateQueries({ queryKey: ['reading-progress'] })
          }}
          className="min-w-0 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-left text-xs transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <span className="block truncate text-[var(--lumi-text-primary)]">{item.entryRef}</span>
          <span className="text-[var(--lumi-text-tertiary)]">
            {Math.round(item.pct)}%{item.deviceLabel !== '' ? ` · ${item.deviceLabel}` : ''}
          </span>
        </button>
      ))}
    </div>
  )
}
