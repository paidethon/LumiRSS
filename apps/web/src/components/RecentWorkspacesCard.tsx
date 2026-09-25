/** RecentWorkspacesCard — N110 最近工作区（home 桌面折叠区入口）。
 *
 * 数据来自设备本地的 recent-workspaces（per-user 键命名空间，绝不
 * 显示其他账户的记录）；点击 = 一键打开（选中该工作区并导航到
 * workspaces section）。记录点在 WorkspacesPage（打开即记录）。
 */

import { useEffect, useState } from 'react'
import { ChevronDown, Eraser } from 'lucide-react'
import {
  clearRecentWorkspaces,
  listRecentWorkspaces,
  RECENT_WORKSPACES_LIMIT,
  type RecentWorkspaceEntry,
} from '../lib/recent-workspaces'
import { useAuthStore } from '../store/auth'
import { useReaderUi } from '../store/reader-ui'
import { cx } from './ui/cx'

export default function RecentWorkspacesCard() {
  const userId = useAuthStore((s) => s.identity?.userId ?? '')
  const selectSection = useReaderUi((s) => s.selectSection)
  const [open, setOpen] = useState(true)
  const [items, setItems] = useState<RecentWorkspaceEntry[]>([])

  useEffect(() => {
    setItems(listRecentWorkspaces(userId))
    const onStorage = () => setItems(listRecentWorkspaces(userId))
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [userId])

  if (items.length === 0) return null

  return (
    <section aria-label="最近工作区" data-testid="recent-workspaces" className="px-2 py-1">
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
          最近工作区（上限 {RECENT_WORKSPACES_LIMIT}）
        </button>
        <button
          type="button"
          aria-label="清除最近工作区记录"
          onClick={() => setItems(clearRecentWorkspaces(userId))}
          className="rounded-[var(--lumi-radius-md)] p-1 text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-secondary)]"
        >
          <Eraser aria-hidden className="size-3.5" />
        </button>
      </div>
      {open && (
        <ul className="mt-0.5 flex flex-col">
          {items.map((entry) => (
            <li key={entry.workspaceId}>
              <button
                type="button"
                data-testid="recent-workspace-entry"
                onClick={() => {
                  selectSection('workspaces')
                  // 打开语义 = 选中该工作区（WorkspacesPage 挂载/更新后
                  // 命中同一 id；跨会话的选中由页面自身状态承载）。
                  const params = new URLSearchParams(window.location.search)
                  params.set('workspace', entry.workspaceId)
                  window.history.replaceState(null, '', `?${params.toString()}`)
                  document.dispatchEvent(new CustomEvent('lumi:open-workspace', { detail: entry.workspaceId }))
                }}
                className="flex min-h-8 w-full items-center gap-2 rounded-[var(--lumi-radius-md)] px-2 py-1 text-left text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] max-lg:min-h-11"
              >
                <span className="min-w-0 flex-1 truncate">{entry.name !== '' ? entry.name : entry.workspaceId}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
