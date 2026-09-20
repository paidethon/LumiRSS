/** AuthorAggregatesPanel — F023 跨来源作者聚合（SearchPage 侧工具）。
 *
 * 作者列表（计数）→ 点开看条目 →「合并到…」（把当前写法并入另一作者，
 * 显式建立别名，绝不自动按同形归并）→「取消合并」删除别名。
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, UserRound, Users } from 'lucide-react'
import type { AuthorSummaryView } from '../api/client'
import {
  useAuthorAliases,
  useAuthorAliasMutations,
  useAuthorItems,
  useAuthors,
} from '../api/queries'
import { Button } from './ui/Button'

function AuthorRow({
  entry,
  allAuthors,
}: {
  entry: AuthorSummaryView
  allAuthors: AuthorSummaryView[]
}) {
  const [open, setOpen] = useState(false)
  const [merging, setMerging] = useState(false)
  const [mergeTarget, setMergeTarget] = useState('')
  const [error, setError] = useState<string | null>(null)
  const items = useAuthorItems(open ? entry.author : null)
  const aliases = useAuthorAliases()
  const { create, remove } = useAuthorAliasMutations()

  const aliasesFor = (aliases.data?.items ?? []).filter(
    (alias) => alias.canonical === entry.author,
  )

  function submitMerge() {
    if (!mergeTarget || mergeTarget === entry.author) return
    create.mutate(
      { alias: entry.author, canonical: mergeTarget },
      {
        onSuccess: () => {
          setMerging(false)
          setMergeTarget('')
        },
        onError: () => setError('合并失败，请检查两个作者名。'),
      },
    )
  }

  return (
    <li className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs" data-lumi-author-row="">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? '收起' : '展开'}作者 ${entry.author}`}
          onClick={() => setOpen((v) => !v)}
          className="flex min-h-7 items-center gap-1 px-1 text-[var(--lumi-text-secondary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          {open ? <ChevronDown aria-hidden className="size-3.5" /> : <ChevronRight aria-hidden className="size-3.5" />}
          <UserRound aria-hidden className="size-3.5" />
        </button>
        <span className="min-w-0 flex-1 truncate font-medium text-[var(--lumi-text-primary)]">
          {entry.author}
        </span>
        <span className="text-[var(--lumi-text-tertiary)]">{entry.count}</span>
        <Button variant="ghost" size="sm" onClick={() => setMerging((v) => !v)}>
          合并到…
        </Button>
      </div>
      {merging ? (
        <div className="mt-1 flex items-center gap-1.5 px-1">
          <select
            aria-label={`把 ${entry.author} 合并到`}
            value={mergeTarget}
            onChange={(e) => setMergeTarget(e.target.value)}
            className="min-h-8 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
          >
            <option value="">选择目标作者…</option>
            {allAuthors
              .filter((a) => a.author !== entry.author)
              .map((a) => (
                <option key={a.author} value={a.author}>
                  {a.author}（{a.count}）
                </option>
              ))}
          </select>
          <Button size="sm" variant="secondary" onClick={submitMerge} disabled={create.isPending}>
            确认合并
          </Button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="mt-1 px-1 text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {aliasesFor.map((alias) => (
        <p key={alias.alias} className="mt-1 flex items-center gap-1 px-1 text-[var(--lumi-text-tertiary)]">
          别名「{alias.alias}」→ {alias.canonical}
          <button
            type="button"
            aria-label={`取消合并 ${alias.alias}`}
            className="underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            onClick={() => remove.mutate(alias.alias)}
          >
            取消合并
          </button>
        </p>
      ))}
      {open ? (
        <ul className="mt-1 flex flex-col gap-1 border-t border-[var(--lumi-separator)] pt-1">
          {items.isPending ? <li className="text-[var(--lumi-text-tertiary)]">加载中…</li> : null}
          {items.isError ? (
            <li role="alert" className="text-[var(--lumi-danger)]">
              条目加载失败。
            </li>
          ) : null}
          {(items.data?.items ?? []).map((item) => (
            <li key={item.entryRef} className="truncate text-[var(--lumi-text-secondary)]">
              {item.title}
            </li>
          ))}
          {!items.isPending && !items.isError && (items.data?.items ?? []).length === 0 ? (
            <li className="text-[var(--lumi-text-tertiary)]">没有条目。</li>
          ) : null}
        </ul>
      ) : null}
    </li>
  )
}

export default function AuthorAggregatesPanel() {
  const authors = useAuthors()
  if (authors.isPending || authors.isError) return null
  const items = authors.data?.items ?? []
  if (items.length === 0) return null
  return (
    <details className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2" data-lumi-authors-panel="">
      <summary className="flex cursor-pointer select-none items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <Users aria-hidden className="size-3.5" />
        作者（{items.length}）
      </summary>
      <ul className="mt-2 flex flex-col gap-1.5">
        {items.map((entry) => (
          <AuthorRow key={entry.author} entry={entry} allAuthors={items} />
        ))}
      </ul>
    </details>
  )
}
