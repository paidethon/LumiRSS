/** RecentReadsInline — F057 最近阅读桌面入口（Sidebar 折叠区）。
 *
 * 与 RecentReads（移动端覆盖层）共用 recent-reads 单一真源（list/
 * clear/enable，上限复用 RECENT_READS_LIMIT）；点击跳转 + 位置恢复
 * （selectEntry 打开文章，Reader 既有 reading-position 自动恢复）；
 * 桌面同样提供「暂停记录 / 清除」。继续阅读（F056 服务端）另由
 * ContinueReadingCard 承载，本组件保持本地历史语义。
 */

import { useEffect, useState } from 'react'
import { ChevronDown, Eraser, Pause, Play } from 'lucide-react'
import {
  clearRecentReads,
  isRecentReadsEnabled,
  listRecentReads,
  RECENT_READS_LIMIT,
  removeRecentRead,
  setRecentReadsEnabled,
  type RecentReadEntry,
} from '../lib/recent-reads'
import { useReaderUi } from '../store/reader-ui'
import { cx } from './ui/cx'

export default function RecentReadsInline() {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const [open, setOpen] = useState(true)
  const [enabled, setEnabled] = useState(true)
  const [items, setItems] = useState<RecentReadEntry[]>([])

  const reload = () => {
    setItems(listRecentReads())
    setEnabled(isRecentReadsEnabled())
  }

  useEffect(() => {
    reload()
    const onStorage = () => reload()
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  if (items.length === 0) return null

  return (
    <section aria-label="最近打开" className="px-2 py-1">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex flex-1 items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-xs font-medium text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <ChevronDown
            aria-hidden
            className={cx('size-3.5 transition-transform duration-[var(--lumi-motion-fast)]', !open && '-rotate-90')}
          />
          最近打开（上限 {RECENT_READS_LIMIT}）
        </button>
        <button
          type="button"
          aria-label={enabled ? '暂停记录最近打开' : '恢复记录最近打开'}
          title={enabled ? '暂停记录' : '恢复记录'}
          onClick={() => {
            setRecentReadsEnabled(!enabled)
            setEnabled(!enabled)
          }}
          className="flex size-6 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
        >
          {enabled ? <Pause aria-hidden className="size-3.5" /> : <Play aria-hidden className="size-3.5" />}
        </button>
        <button
          type="button"
          aria-label="清除最近打开"
          title="清除"
          onClick={() => setItems(clearRecentReads())}
          className="flex size-6 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
        >
          <Eraser aria-hidden className="size-3.5" />
        </button>
      </div>
      {open && (
        <ul className="mt-1 flex flex-col">
          {items.map((item) => (
            <li key={item.entryRef} className="group flex items-center gap-1">
              <button
                type="button"
                onClick={() => {
                  selectEntry(item.entryRef)
                }}
                className="min-w-0 flex-1 truncate rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-left text-xs text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
                title={item.title}
              >
                {item.title}
              </button>
              <button
                type="button"
                aria-label={`移除 ${item.title}`}
                onClick={() => setItems(removeRecentRead(item.entryRef))}
                className="hidden size-5 items-center justify-center rounded text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)] group-hover:flex"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
