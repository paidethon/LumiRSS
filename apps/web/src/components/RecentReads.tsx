/** RecentReads — F10 最近阅读面板（本地历史，简单覆盖层，非 Sheet）。
 *
 * 数据源：lib/recent-reads（localStorage `lumirss-recent-reads`，最多
 * 30 条，记录点在 EntryCard/EntryRow 行点击）。面板职责：
 * - 打开时读取历史（标题 + 来源 + 相对时间 formatRelativeTime）；
 * - 点条目 = recordRecentRead（置顶刷新时间）+ selectEntry（不标已读，
 *   与列表行同一语义）+ 关闭面板；
 * - 单条移除 / 清空全部 / 记录开关（isRecentReadsEnabled）；
 * - 空态诚实：「还没有阅读记录」+ 记录点说明；
 * - 关闭记录开关后显示提示（历史保留但不再新增）。
 *
 * 覆盖层实现刻意轻量（fixed div + role=dialog + aria-modal + Escape），
 * 不走 Sheet/Dialog primitive：面板从移动抽屉内唤起（同级浮层），需要
 * 自持 z 层级且不与抽屉的 Base UI Drawer 行为叠加。z 取 dialog+1，
 * 保证盖在抽屉之上。 */

import { useEffect, useId, useRef, useState } from 'react'
import { History, Trash2, X } from 'lucide-react'
import { useReaderUi } from '../store/reader-ui'
import { acquireTopmostOverlay, isTopmostOverlay } from '../lib/overlay-stack'
import {
  clearRecentReads,
  isRecentReadsEnabled,
  listRecentReads,
  recordRecentRead,
  removeRecentRead,
  setRecentReadsEnabled,
  type RecentReadEntry,
} from '../lib/recent-reads'
import { formatRelativeTime } from '../lib/date-format'
import { EmptyState } from './ui/EmptyState'
import { cx } from './ui/cx'

export default function RecentReads({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const selectEntry = useReaderUi((s) => s.selectEntry)
  const [items, setItems] = useState<RecentReadEntry[]>([])
  const [enabled, setEnabled] = useState(true)

  // 每次打开重新读取（localStorage 是真源，面板不持缓存）
  useEffect(() => {
    if (!open) return
    setItems(listRecentReads())
    setEnabled(isRecentReadsEnabled())
  }, [open])

  // FIX-103：Escape 只在本面板是「最上层浮层」时关闭本面板。面板从导航
  // 抽屉（Base UI Drawer）之上唤起：旧实现挂 window bubble 监听，一次
  // Escape 会与抽屉的 Base UI 监听各自为政、同时关两层。改为 window
  // capture（先于 Base UI 的 document bubble 监听）+ overlay-stack 顶层
  // 门控；确属最上层时 stopPropagation，下层收不到这次按键。
  const overlayId = `recent-reads-${useId()}`
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    if (!open) return
    const release = acquireTopmostOverlay(overlayId)
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      // IME 组合中的 Escape 交还原生取消行为
      if (event.isComposing || event.keyCode === 229) return
      if (!isTopmostOverlay(overlayId)) return
      event.preventDefault()
      event.stopPropagation()
      onCloseRef.current()
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => {
      release()
      window.removeEventListener('keydown', onKeyDown, true)
    }
  }, [open, overlayId])

  if (!open) return null

  const openEntry = (item: RecentReadEntry) => {
    // 再开一次 = 置顶刷新时间（LRU 语义）
    recordRecentRead({
      entryRef: item.entryRef,
      feedTitle: item.feedTitle,
      title: item.title,
    })
    selectEntry(item.entryRef)
    onClose()
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="最近阅读"
      data-testid="recent-reads-panel"
      className="fixed inset-0 z-[calc(var(--lumi-z-dialog)_+_1)] flex items-end justify-center sm:items-center"
    >
      {/* 遮罩（点击关闭） */}
      <button
        type="button"
        aria-label="关闭最近阅读"
        onClick={onClose}
        className="absolute inset-0 size-full cursor-default bg-[var(--lumi-text-primary)]/30"
      />
      <div className="relative flex max-h-[80dvh] w-full flex-col overflow-hidden rounded-t-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)] sm:max-w-md sm:rounded-[var(--lumi-radius-xl)]">
        {/* 头部：标题 + 关闭 */}
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--lumi-separator)] px-4 py-2.5">
          <History aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
          <h2 className="min-w-0 flex-1 text-sm font-semibold text-[var(--lumi-text-primary)]">
            最近阅读
          </h2>
          <button
            type="button"
            onClick={() => {
              clearRecentReads()
              setItems([])
            }}
            disabled={items.length === 0}
            aria-label="清空最近阅读"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 aria-hidden className="size-4" />
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <X aria-hidden className="size-4" />
          </button>
        </div>

        {/* 记录开关（设备本地偏好） */}
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--lumi-separator)] px-4 py-2">
          <span className="min-w-0 flex-1 text-xs text-[var(--lumi-text-secondary)]">
            记录最近阅读
            <span className="ml-1 text-[var(--lumi-text-tertiary)]">
              （打开文章时自动记录，仅存本机）
            </span>
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="记录最近阅读开关"
            data-testid="recent-reads-toggle"
            onClick={() => {
              const next = !enabled
              setRecentReadsEnabled(next)
              setEnabled(next)
            }}
            className={cx(
              'relative h-6 w-11 shrink-0 rounded-full border transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              enabled
                ? 'border-transparent bg-[var(--lumi-accent)]'
                : 'border-[var(--lumi-border)] bg-[var(--lumi-surface-hover)]',
            )}
          >
            <span
              aria-hidden="true"
              className={cx(
                // FIX-111：thumb 位移走 transform（transition-transform），
                // 不用 transition-all/left——只动画 cheap property。
                'absolute left-0.5 top-0.5 size-4.5 rounded-full bg-white shadow transition-transform duration-[var(--lumi-motion-fast)]',
                enabled ? 'translate-x-[1.25rem]' : 'translate-x-0',
              )}
            />
          </button>
        </div>

        {/* 历史 / 空态 */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {items.length === 0 ? (
            <EmptyState
              icon={<History aria-hidden className="size-8" />}
              title="还没有阅读记录"
              description="打开文章时会自动记录（仅存本机，最多 30 条）；可随时在上方关闭记录。"
              className="py-10"
            />
          ) : (
            <ul aria-label="最近阅读列表">
              {items.map((item) => (
                <li key={item.entryRef} className="flex items-stretch border-b border-[var(--lumi-separator)] last:border-b-0">
                  <button
                    type="button"
                    onClick={() => openEntry(item)}
                    className="flex min-h-14 min-w-0 flex-1 flex-col justify-center gap-0.5 px-4 py-2 text-left transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  >
                    <span className="line-clamp-1 text-sm font-medium text-[var(--lumi-text-primary)]">
                      {item.title !== '' ? item.title : '未命名文章'}
                    </span>
                    <span className="flex min-w-0 items-center gap-1.5 text-xs text-[var(--lumi-text-tertiary)]">
                      <span className="truncate">{item.feedTitle !== '' ? item.feedTitle : '来源未知'}</span>
                      <span aria-hidden>·</span>
                      <span className="shrink-0">{formatRelativeTime(item.openedAt)}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setItems(removeRecentRead(item.entryRef))}
                    aria-label={`移除「${item.title !== '' ? item.title : '未命名文章'}」`}
                    className="flex w-11 shrink-0 items-center justify-center text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  >
                    <X aria-hidden className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {items.length > 0 && !enabled && (
            <p role="note" className="px-4 py-2 text-xs text-[var(--lumi-text-tertiary)]">
              记录已关闭：现有历史保留，但不再新增。
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
