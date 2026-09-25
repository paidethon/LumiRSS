/** StagedSourcesSection — N016：来源页「待评估」区。
 *
 * 暂存池（staged_sources）：URL 经有界预览抓取后暂存（≤10 条元数据
 * 快照），NOT subscribed / 不计入未读。每行可展开样例预览、订阅
 * （走正常订阅路径恰好一次；已订阅 → exists，暂存行移除）或丢弃。
 * N011 组合包导入的凭据草稿（origin=bundle_draft, enabled=0）也在
 * 本列表如实呈现：不可直接订阅，需在 Lumi 重建来源。
 *
 * 所有 HTTP 经 src/api/client.ts；状态全部来自 TanStack Query。
 */

import { useState } from 'react'
import { ChevronDown, FlaskConical, Rss, Trash2 } from 'lucide-react'
import {
  useDiscardStagedSourceMutation,
  useStagedSources,
  useSubscribeStagedSourceMutation,
} from '../api/queries'
import type { StagedSource } from '../api/client'
import { formatTimestamp } from '../lib/date-format'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

function errorText(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message
  return fallback
}

/** 单行：标题 / URL / 样例预览（可折叠）/ 订阅、丢弃。 */
function StagedRow({ row }: { row: StagedSource }) {
  const subscribe = useSubscribeStagedSourceMutation()
  const discard = useDiscardStagedSourceMutation()
  const [open, setOpen] = useState(false)
  const isDraft = row.origin === 'bundle_draft'

  return (
    <li
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5"
      data-staged-row={row.id}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
            {row.title !== '' ? row.title : row.url}
            {isDraft && (
              <span className="ml-1.5 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                凭据草稿（停用）
              </span>
            )}
            {row.subscribed && !isDraft && (
              <span className="ml-1.5 text-[10px] text-[var(--lumi-text-tertiary)]">已订阅</span>
            )}
          </p>
          <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]" title={row.url}>
            {row.url}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            暂存于 {formatTimestamp(row.addedAt)}
            {row.note != null && row.note !== '' ? ` · ${row.note}` : ''}
          </p>
          {row.sample.length > 0 && (
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
              className="mt-1 flex items-center gap-1 rounded-[var(--lumi-radius-md)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
            >
              <ChevronDown
                aria-hidden
                className={cx('size-3 transition-transform duration-[var(--lumi-motion-fast)]', open && 'rotate-180')}
              />
              样例预览（{row.sample.length} 条）
            </button>
          )}
          {open && (
            <ul className="mt-1.5 flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              {row.sample.map((entry, i) => (
                <li key={i} className="min-w-0 text-[11px] leading-relaxed">
                  <span className="font-medium text-[var(--lumi-text-primary)]">{entry.title}</span>
                  {entry.summary != null && entry.summary !== '' && (
                    <span className="text-[var(--lumi-text-tertiary)]"> · {entry.summary}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {subscribe.isError && (
            <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
              {errorText(subscribe.error, '订阅失败。')}
            </p>
          )}
          {discard.isError && (
            <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
              {errorText(discard.error, '丢弃失败。')}
            </p>
          )}
        </div>
        {!isDraft && (
          <Button
            variant="secondary"
            size="sm"
            disabled={subscribe.isPending}
            onClick={() => subscribe.mutate(row.id)}
            data-staged-subscribe={row.id}
          >
            <Rss aria-hidden className="size-3.5" />
            {subscribe.isPending && subscribe.variables === row.id ? '订阅中…' : '订阅'}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          disabled={discard.isPending}
          onClick={() => discard.mutate(row.id)}
          aria-label={`丢弃 ${row.title !== '' ? row.title : row.url}`}
          data-staged-discard={row.id}
        >
          <Trash2 aria-hidden className="size-3.5" />
        </Button>
      </div>
    </li>
  )
}

/** 来源页底部：待评估（暂存池）区。空池不占版面。 */
export function StagedSourcesSection() {
  const staged = useStagedSources()
  if (staged.isPending || staged.isError || staged.data.items.length === 0) {
    // 加载中 / 出错时静默收起：暂存池是辅助区，不打断来源总览主视图。
    return null
  }
  const staging = staged.data.items.filter((row) => row.origin === 'staging')
  const drafts = staged.data.items.filter((row) => row.origin !== 'staging')
  if (staging.length === 0 && drafts.length === 0) return null

  return (
    <section aria-label="待评估来源" className="mt-5 flex flex-col gap-1.5">
      <h2 className="flex items-center gap-1.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--lumi-text-tertiary)]">
        <FlaskConical aria-hidden className="size-3.5" />
        待评估
      </h2>
      <p className="px-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
        暂存的来源不订阅、不计入未读；确认后再订阅或丢弃。
      </p>
      <ul className="flex flex-col gap-1.5">
        {staging.map((row) => (
          <StagedRow key={row.id} row={row} />
        ))}
        {drafts.map((row) => (
          <StagedRow key={row.id} row={row} />
        ))}
      </ul>
    </section>
  )
}
