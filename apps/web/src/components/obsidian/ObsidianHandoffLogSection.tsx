/** ObsidianHandoffLogSection — N140「交接记录」：双向（导出/打开/导入
 * 确认）历史 + 状态徽章 + 显式确认 + 清理。
 *
 * 诚实语义：
 * - confirmed 只能由用户【显式】点击「我已在 Obsidian 保存」产生；
 *   页面加载 / 重新渲染等被动事件绝不自动确认（服务端也无此路径）；
 * - 记录只是辅助痕迹：清理 = 删除全部历史（服务端如实返回条数），
 *   绝不冒充「同步状态」。 */

import { useState } from 'react'
import { CheckCircle2, CircleDashed, History, Loader2, Trash2 } from 'lucide-react'
import type { ObsidianHandoffLogEntry } from '../../api/client'
import {
  useClearObsidianHandoffLogMutation,
  useConfirmObsidianHandoffMutation,
  useObsidianHandoffLog,
} from '../../api/queries'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const DIRECTION_LABELS: Record<string, string> = {
  export: '导出',
  open: '打开',
  import_confirm: '导入确认',
}

function StatusChip({ status }: { status: ObsidianHandoffLogEntry['status'] }) {
  const confirmed = status === 'confirmed'
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1 rounded-[var(--lumi-radius-full)] border px-2 py-0.5 text-[11px]',
        confirmed
          ? 'border-[var(--lumi-accent-text)] text-[var(--lumi-accent-text)]'
          : 'border-[var(--lumi-border)] text-[var(--lumi-text-tertiary)]',
      )}
      aria-label={confirmed ? '状态：已确认' : '状态：待确认'}
    >
      {confirmed ? (
        <CheckCircle2 aria-hidden className="size-3" />
      ) : (
        <CircleDashed aria-hidden className="size-3" />
      )}
      {confirmed ? '已确认' : '待确认'}
    </span>
  )
}

function HandoffLogRow({ entry }: { entry: ObsidianHandoffLogEntry }) {
  const confirm = useConfirmObsidianHandoffMutation()
  return (
    <li
      className="flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2"
      data-lumi-handoff-log-entry={entry.id}
    >
      <span className="text-xs font-medium text-[var(--lumi-text-primary)]">
        {DIRECTION_LABELS[entry.direction] ?? entry.direction}
      </span>
      <StatusChip status={entry.status} />
      <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-tertiary)]">
        {entry.noteName !== '' ? entry.noteName : '（未命名）'}
        {entry.entryRef !== '' ? ` · ${entry.entryRef}` : ''}
      </span>
      {entry.status === 'pending' && (
        <Button
          size="sm"
          variant="secondary"
          disabled={confirm.isPending}
          aria-label={`确认交接 ${entry.noteName || entry.id} 已在 Obsidian 保存`}
          onClick={() => confirm.mutate(entry.id)}
        >
          {confirm.isPending ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : null}
          我已在 Obsidian 保存
        </Button>
      )}
    </li>
  )
}

export default function ObsidianHandoffLogSection() {
  const log = useObsidianHandoffLog()
  const clear = useClearObsidianHandoffLogMutation()
  const [open, setOpen] = useState(false)

  const items = log.data?.items ?? []

  return (
    <section
      aria-label="交接记录"
      className="border-t border-[var(--lumi-separator)] px-3 py-4 max-lg:pb-[84px]"
      data-lumi-handoff-log-section=""
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-[var(--lumi-radius-md)] px-1 py-1.5 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      >
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">交接记录</h2>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          {open ? '收起' : `展开（${items.length} 条）`}
        </span>
      </button>

      <p className="mt-1.5 px-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        导出到 Obsidian / 打开笔记会留下「待确认」记录；只有你亲自点「我已在 Obsidian
        保存」才会变为「已确认」——重新加载页面不会自动确认。记录只是交接痕迹，
        不是你的笔记本身。
      </p>

      {open && (
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex items-center gap-2">
            {!log.isPending && items.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                disabled={clear.isPending}
                aria-label="清理交接记录"
                onClick={() => clear.mutate()}
              >
                <Trash2 aria-hidden className="size-3.5" />
                {clear.isPending ? '清理中…' : '清理'}
              </Button>
            )}
            {clear.isSuccess && (
              <span role="status" className="text-xs text-[var(--lumi-accent-text)]">
                已清理 {clear.data.cleared} 条记录
              </span>
            )}
          </div>
          {log.isPending ? (
            <ul className="flex flex-col gap-2" aria-label="交接记录加载中">
              {[0, 1].map((i) => (
                <li key={i}>
                  <Skeleton className="h-11 w-full" />
                </li>
              ))}
            </ul>
          ) : log.isError ? (
            <div className="flex flex-col gap-2">
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                交接记录加载失败：{log.error.message}
              </p>
              <Button size="sm" variant="secondary" onClick={() => log.refetch()}>
                重试
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div
              className="flex items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-dashed border-[var(--lumi-border)] px-3 py-3 text-xs text-[var(--lumi-text-tertiary)]"
              data-lumi-handoff-log-empty=""
            >
              <History aria-hidden className="size-3.5" />
              还没有交接记录。在阅读页使用「导出到 Obsidian」后会出现在这里。
            </div>
          ) : (
            <ul className="flex flex-col gap-2" aria-label="交接记录列表">
              {items.map((entry) => (
                <HandoffLogRow key={entry.id} entry={entry} />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
