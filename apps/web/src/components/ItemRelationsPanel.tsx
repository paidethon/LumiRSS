/** ItemRelationsPanel — F021 手工关联内容（阅读器侧边）。
 *
 * 列出当前条目的手工关联（双向；失效端诚实标注「已失效」，点击不跳转），
 * 支持解除；「关联内容」打开对话框：搜索选择另一条 + 备注 → 创建。
 * 全程无 AI 参与：搜索走既有 /api/v1/search，创建走 /api/v1/relations。
 */

import { useState } from 'react'
import { Link2, Loader2, Plus, Unlink } from 'lucide-react'
import {
  searchEntries,
  type ItemRelationView,
} from '../api/client'
import {
  useCreateRelationMutation,
  useDeleteRelationMutation,
  useItemRelations,
} from '../api/queries'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

function RelationRow({ relation, selfRef }: { relation: ItemRelationView; selfRef: string }) {
  const remove = useDeleteRelationMutation()
  const other = relation.srcRef === selfRef ? relation.dst : relation.src
  const otherRef = relation.srcRef === selfRef ? relation.dstRef : relation.srcRef
  const stale = other.stale
  return (
    <li className="flex items-start justify-between gap-2" data-lumi-relation-row="">
      <div className="min-w-0 flex-1">
        {stale ? (
          <span
            className="block truncate text-xs text-[var(--lumi-text-secondary)]"
            title="内容已失效，无法跳转"
          >
            已失效 · {otherRef}
          </span>
        ) : (
          <span className="block truncate text-xs font-medium text-[var(--lumi-text-primary)]">
            {other.title}
          </span>
        )}
        {relation.note ? (
          <span className="block truncate text-xs text-[var(--lumi-text-secondary)]">
            {relation.note}
          </span>
        ) : null}
      </div>
      <IconButton
        size="sm"
        icon={<Unlink aria-hidden className="size-4" />}
        label={`解除关联：${stale ? '已失效条目' : other.title}`}
        disabled={remove.isPending}
        onClick={() => remove.mutate(relation.id)}
      />
    </li>
  )
}

function CreateRelationDialog({
  open,
  onClose,
  selfRef,
}: {
  open: boolean
  onClose: () => void
  selfRef: string
}) {
  const [query, setQuery] = useState('')
  const [note, setNote] = useState('')
  const [candidates, setCandidates] = useState<
    Array<{ entryRef: string; title: string }>
  >([])
  const [selected, setSelected] = useState<{ entryRef: string; title: string } | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const create = useCreateRelationMutation()

  async function runSearch() {
    const clean = query.trim()
    if (!clean) return
    setSearching(true)
    setError(null)
    try {
      const page = await searchEntries({ q: clean, limit: 10 })
      const options = page.items
        .map((item) => ({ entryRef: item.entryRef, title: item.title }))
        .filter((item) => `rss:${item.entryRef}` !== selfRef)
      setCandidates(options)
      if (options.length === 0) setError('没有匹配的条目。')
    } catch {
      setError('搜索失败，请稍后重试。')
    } finally {
      setSearching(false)
    }
  }

  function submit() {
    if (!selected) return
    setError(null)
    create.mutate(
      { srcRef: selfRef, dstRef: `rss:${selected.entryRef}`, note },
      {
        onSuccess: () => {
          setSelected(null)
          setQuery('')
          setNote('')
          setCandidates([])
          onClose()
        },
        onError: (err) => {
          setError(
            err instanceof Error && /409|duplicate/i.test(err.message)
              ? '该关联已存在（备注不同）。'
              : '创建失败：请检查两条内容是否有效。',
          )
        },
      },
    )
  }

  return (
    <Dialog open={open} onClose={onClose} title="关联内容">
      <div className="flex flex-col gap-3 text-sm">
        {!selected ? (
          <>
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void runSearch()
                  }
                }}
                placeholder="按标题/正文搜索要关联的条目"
                className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm"
                aria-label="搜索要关联的条目"
              />
              <Button variant="secondary" onClick={() => void runSearch()} disabled={searching}>
                {searching ? <Loader2 aria-hidden className="size-4 animate-spin" /> : '搜索'}
              </Button>
            </div>
            <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
              {candidates.map((candidate) => (
                <li key={candidate.entryRef}>
                  <button
                    type="button"
                    className="w-full truncate rounded-[var(--lumi-radius-md)] px-2 py-2 text-left text-xs hover:bg-[var(--lumi-surface-hover)]"
                    onClick={() => {
                      setSelected(candidate)
                      setCandidates([])
                    }}
                  >
                    {candidate.title}
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-2 text-xs">
            关联到：<span className="font-medium">{selected.title}</span>
            <button
              type="button"
              className="ml-2 text-[var(--lumi-text-secondary)] underline"
              onClick={() => setSelected(null)}
            >
              重选
            </button>
          </p>
        )}
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="备注（可选，如「同一事件的两面」）"
          className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm"
          aria-label="关联备注"
          maxLength={500}
        />
        {error ? (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {error}
          </p>
        ) : null}
      </div>
      <footer className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          取消
        </Button>
        <Button onClick={submit} disabled={!selected || create.isPending}>
          创建关联
        </Button>
      </footer>
    </Dialog>
  )
}

export default function ItemRelationsPanel({ itemRef }: { itemRef: string }) {
  const relations = useItemRelations(itemRef)
  const [open, setOpen] = useState(false)
  if (relations.isPending || relations.isError) return null
  const items = relations.data?.items ?? []
  return (
    <section
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-sm"
      data-lumi-item-relations=""
    >
      <div className={cx('flex items-center justify-between')}>
        <span className="flex items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)]">
          <Link2 aria-hidden className="size-3.5" />
          关联内容（{items.length}）
        </span>
        <IconButton
          size="sm"
          icon={<Plus aria-hidden className="size-4" />}
          label="关联内容"
          onClick={() => setOpen(true)}
        />
      </div>
      {items.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-2 border-t border-[var(--lumi-separator)] pt-2">
          {items.map((relation) => (
            <RelationRow key={relation.id} relation={relation} selfRef={itemRef} />
          ))}
        </ul>
      ) : null}
      <CreateRelationDialog
        open={open}
        onClose={() => setOpen(false)}
        selfRef={itemRef}
      />
    </section>
  )
}
