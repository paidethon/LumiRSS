/** SearchBasketPanel — N147 搜索结果暂存篮面板（SearchPage）。
 *
 * - 列出暂存引用（设备本地 localStorage，上限 100，跨页保留）；
 * - 批量加入工作区：逐条调用既有 workspace add_item（`rss:<entryRef>`），
 *   部分失败逐条诚实列出，绝不静默吞掉；
 * - 导出：markdown 引用清单（与 F073 导出同一字段口径，客户端下载）；
 * - 清空（显式动作，不做隐式清除）。
 */

import { useMemo, useState } from 'react'
import { useWorkspaces } from '../api/queries'
import { addWorkspaceItem } from '../api/client'
import { ShoppingBasket, Download, Trash2 } from 'lucide-react'
import {
  basketToMarkdown,
  SEARCH_BASKET_LIMIT,
  useSearchBasket,
} from '../store/search-basket'
import { Button } from './ui/Button'

interface BatchOutcome {
  ok: number
  failures: { entryRef: string; reason: string }[]
}

function downloadMarkdown(content: string): void {
  const blob = new Blob([content], { type: 'text/markdown; charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'lumi-search-basket.md'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function SearchBasketPanel() {
  const items = useSearchBasket((s) => s.items)
  const remove = useSearchBasket((s) => s.remove)
  const clear = useSearchBasket((s) => s.clear)
  const workspaces = useWorkspaces()
  const workspaceList = useMemo(
    () => (Array.isArray(workspaces.data) ? workspaces.data : (workspaces.data?.items ?? [])),
    [workspaces.data],
  )
  const usableWorkspaces = workspaceList.filter((w) => !w.archived)
  const [workspaceId, setWorkspaceId] = useState('')
  const [batch, setBatch] = useState<BatchOutcome | null>(null)
  const [batchPending, setBatchPending] = useState(false)

  const effectiveWorkspaceId =
    workspaceId !== '' && usableWorkspaces.some((w) => w.id === workspaceId)
      ? workspaceId
      : (usableWorkspaces[0]?.id ?? '')

  const addToWorkspace = async () => {
    if (effectiveWorkspaceId === '' || items.length === 0) return
    setBatchPending(true)
    setBatch(null)
    const outcome: BatchOutcome = { ok: 0, failures: [] }
    // 逐条调用（每条独立成败），失败带原因诚实列出。
    for (const item of items) {
      try {
        await addWorkspaceItem(effectiveWorkspaceId, `rss:${item.entryRef}`)
        outcome.ok += 1
      } catch (error) {
        outcome.failures.push({
          entryRef: item.entryRef,
          reason: error instanceof Error ? error.message : '未知错误',
        })
      }
    }
    setBatch(outcome)
    setBatchPending(false)
  }

  if (items.length === 0) {
    return (
      <div
        data-testid="basket-panel"
        className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
        aria-label="暂存篮"
      >
        <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
          <ShoppingBasket aria-hidden className="size-3.5" />
          暂存篮（0）
        </p>
        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          在搜索结果行勾选「加入暂存篮」，引用会保留在本机（上限 {SEARCH_BASKET_LIMIT} 条；登出后清空）。
        </p>
      </div>
    )
  }

  return (
    <div
      data-testid="basket-panel"
      className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      aria-label="暂存篮"
    >
      <p className="flex items-center gap-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <ShoppingBasket aria-hidden className="size-3.5" />
        暂存篮（{items.length}
        {items.length >= SEARCH_BASKET_LIMIT ? `，已达上限 ${SEARCH_BASKET_LIMIT}` : ''}）
      </p>

      <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto" aria-label="暂存条目">
        {items.map((item) => (
          <li
            key={item.entryRef}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] px-1.5 py-1 text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            <span className="min-w-0 flex-1 truncate" title={item.title}>
              {item.title || item.entryRef}
            </span>
            <span className="shrink-0 text-[11px] text-[var(--lumi-text-tertiary)]">
              {item.feedTitle}
            </span>
            <button
              type="button"
              onClick={() => remove(item.entryRef)}
              aria-label={`从暂存篮移除「${item.title || item.entryRef}」`}
              className="relative flex size-6 shrink-0 items-center justify-center rounded-full text-[var(--lumi-text-tertiary)] transition-colors after:absolute after:-inset-y-2.5 after:-inset-x-1 after:content-[''] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              <Trash2 aria-hidden className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-2">
        {usableWorkspaces.length > 0 ? (
          <>
            <select
              value={effectiveWorkspaceId}
              onChange={(e) => setWorkspaceId(e.target.value)}
              aria-label="选择工作区"
              className="min-h-7 max-w-48 min-w-0 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
            >
              {usableWorkspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              data-testid="basket-add-to-workspace"
              onClick={() => void addToWorkspace()}
              disabled={batchPending || items.length === 0}
            >
              {batchPending ? '加入中…' : `加入工作区（${items.length}）`}
            </Button>
          </>
        ) : (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">暂无可用工作区。</p>
        )}
        <Button
          size="sm"
          variant="ghost"
          data-testid="basket-export"
          onClick={() => downloadMarkdown(basketToMarkdown(items))}
        >
          <Download aria-hidden className="size-3.5" />
          导出
        </Button>
        <Button size="sm" variant="ghost" onClick={() => { clear(); setBatch(null) }}>
          清空
        </Button>
      </div>

      {batch !== null && (
        <div
          data-testid="basket-batch-result"
          role="status"
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
        >
          <span>
            已加入工作区 {batch.ok} / {items.length} 条。
          </span>
          {batch.failures.length > 0 && (
            <span className="text-[var(--lumi-danger)]">
              失败 {batch.failures.length} 条：
              {batch.failures.map((f) => `${f.entryRef.slice(0, 12)}…（${f.reason}）`).join('；')}
            </span>
          )}
        </div>
      )}
      {workspaces.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          工作区列表加载失败，无法批量加入。
        </p>
      )}
    </div>
  )
}
