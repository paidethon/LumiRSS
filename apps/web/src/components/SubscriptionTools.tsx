/** 订阅管理工具（F004 查重 / F005 备注与维护记录 / F006 批量分类迁移）。
 *
 * F004：只读展示重复候选组（成员 + 差异字段 + 规范化依据），无删除/
 * 合并副作用；F005：备注/理由/维护记录三字段编辑（原文存储、渲染转义）；
 * F006：目标分类选择 + 受影响计数 + 逐项成功/失败 + 仅重试失败项。 */

import { useEffect, useState } from 'react'
import { AlertCircle, Copy, Loader2, NotebookPen } from 'lucide-react'
import {
  useBatchMoveMutation,
  useCategories,
  useDuplicateSuspectsQuery,
  useSourceNotesQuery,
  useUpdateSourceNotesMutation,
} from '../api/queries'
import { managementErrorText } from '../lib/management-errors'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

/** F004 查重面板（只读展示）。 */
export function DuplicateSuspectsPanel() {
  const query = useDuplicateSuspectsQuery(true)
  const groups = query.data?.groups ?? []

  if (query.isPending) {
    return (
      <section
        aria-label="重复订阅检查"
        data-testid="duplicate-panel"
        className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
      >
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-2 h-10 w-full" />
      </section>
    )
  }
  if (query.isError) {
    return (
      <section aria-label="重复订阅检查" className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">查重加载失败</p>
        <Button size="sm" variant="secondary" className="mt-2" onClick={() => query.refetch()}>
          重试
        </Button>
      </section>
    )
  }
  return (
    <section
      aria-label="重复订阅检查"
      data-testid="duplicate-panel"
      className="mb-3 overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]"
    >
      <h3 className="px-3.5 py-2 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        重复候选（{groups.length} 组）· 仅展示，不做任何合并或删除
      </h3>
      {groups.length === 0 ? (
        <div className="border-t border-[var(--lumi-separator)]">
          <EmptyState
            icon={<Copy aria-hidden className="size-6" />}
            title="没有发现重复候选"
            description="不同 URL、不同路径的订阅不会被合并判定（保守规则）。"
          />
        </div>
      ) : (
        <ul className="divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
          {groups.map((group) => (
            <li key={group.key} className="px-3.5 py-2.5" data-testid="duplicate-group">
              <p className="text-xs text-[var(--lumi-text-tertiary)]">
                规范化：{group.key} · 差异：{group.differences.join('、') || '无'}
              </p>
              <ul className="mt-1 flex flex-col gap-1">
                {group.members.map((member) => (
                  <li key={member.subscriptionRef} className="text-sm text-[var(--lumi-text-primary)]">
                    <span className="truncate">{member.title || member.feedUrl}</span>
                    <span className="ml-2 text-xs text-[var(--lumi-text-tertiary)]">{member.feedUrl}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** F005 备注/维护记录对话框（三字段编辑）。 */
export function SourceNotesDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  subscription: { subscriptionRef: string; title: string } | null
}) {
  const notes = useSourceNotesQuery(open && subscription !== null ? subscription.subscriptionRef : null)
  const mutation = useUpdateSourceNotesMutation()
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [log, setLog] = useState('')
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (open) {
      mutation.reset()
      setLoaded(false)
    }
    // reset 是稳定引用；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (notes.data && !loaded) {
    setNote(notes.data.note ?? '')
    setReason(notes.data.reason ?? '')
    setLog(notes.data.maintenanceLog ?? '')
    setLoaded(true)
  }

  const busy = mutation.isPending
  function close() {
    if (busy) return
    onClose()
  }
  function save() {
    if (!subscription || busy) return
    mutation.mutate(
      {
        subscriptionRef: subscription.subscriptionRef,
        note: note.trim() === '' ? null : note,
        reason: reason.trim() === '' ? null : reason,
        maintenanceLog: log.trim() === '' ? null : log,
      },
      { onSuccess: onClose },
    )
  }
  const errorText = mutation.isError ? managementErrorText(mutation.error) : null
  const fields: { id: string; label: string; value: string; set: (v: string) => void }[] = [
    { id: 'source-note', label: '备注', value: note, set: setNote },
    { id: 'source-reason', label: '订阅理由', value: reason, set: setReason },
    { id: 'source-log', label: '维护记录', value: log, set: setLog },
  ]

  return (
    <Dialog
      open={open}
      onClose={close}
      title="备注与维护记录"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>取消</Button>
          <Button variant="primary" onClick={save} disabled={busy}>
            {busy ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" /> 保存中…
              </>
            ) : (
              '保存'
            )}
          </Button>
        </>
      }
    >
      {subscription !== null && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--lumi-text-secondary)]">
            为「{subscription.title}」记录备注、订阅理由与维护记录（留空 = 清空该字段）。
          </p>
          {notes.isPending && <Skeleton className="h-20 w-full" />}
          {fields.map((field) => (
            <div key={field.id} className="flex flex-col gap-1.5">
              <label htmlFor={field.id} className="text-sm font-medium text-[var(--lumi-text-primary)]">
                {field.label}
              </label>
              <textarea
                id={field.id}
                value={field.value}
                onChange={(e) => field.set(e.target.value)}
                rows={2}
                maxLength={20000}
                className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
              />
            </div>
          ))}
          {errorText !== null && (
            <div role="alert" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]">
              {errorText.title}
            </div>
          )}
        </div>
      )}
    </Dialog>
  )
}

/** F006 批量移动对话框（目标选择 + 受影响计数 + 逐项结果 + 重试失败项）。 */
export function BatchMoveDialog({
  open,
  onClose,
  refs,
  titleOf,
}: {
  open: boolean
  onClose: () => void
  refs: string[]
  titleOf: (ref: string) => string
}) {
  const categories = useCategories(true)
  const [target, setTarget] = useState('')
  const [result, setResult] = useState<{ ref: string; ok: boolean; error: string | null }[] | null>(null)
  const mutation = useBatchMoveMutation()

  useEffect(() => {
    if (open) {
      setTarget('')
      setResult(null)
      mutation.reset()
    }
    // 依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function execute(moveRefs: string[]) {
    if (target === '' || busy) return
    mutation.mutate(
      { refs: moveRefs, targetCategoryId: target },
      { onSuccess: (r) => setResult(r.items) },
    )
  }

  const busy = mutation.isPending
  const failedRefs = (result ?? []).filter((i) => !i.ok).map((i) => i.ref)
  const errorText = mutation.isError ? managementErrorText(mutation.error) : null

  return (
    <Dialog
      open={open}
      onClose={() => !busy && onClose()}
      title="移动到分类"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>关闭</Button>
          {result !== null && failedRefs.length > 0 && (
            <Button variant="secondary" disabled={busy || target === ''} onClick={() => execute(failedRefs)}>
              仅重试失败项（{failedRefs.length}）
            </Button>
          )}
          {result === null && (
            <Button variant="primary" disabled={busy || target === '' || refs.length === 0} onClick={() => execute(refs)}>
              {busy ? (
                <>
                  <Loader2 aria-hidden className="size-4 animate-spin" /> 移动中…
                </>
              ) : (
                `移动 ${refs.length} 个订阅`
              )}
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-[var(--lumi-text-secondary)]">
          将 {refs.length} 个订阅移动到目标分类（受影响 {refs.length} 项；逐项执行，失败不中断整批）。
        </p>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="batch-move-target" className="text-sm font-medium text-[var(--lumi-text-primary)]">
            目标分类
          </label>
          <select
            id="batch-move-target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]"
          >
            <option value="">选择分类…</option>
            {(categories.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.label}</option>
            ))}
          </select>
        </div>
        {result !== null && (
          <ul className="max-h-40 divide-y divide-[var(--lumi-separator)] overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
            {result.map((item) => (
              <li key={item.ref} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                {item.ok ? (
                  <span className="text-[var(--lumi-accent-text)]">✓</span>
                ) : (
                  <AlertCircle aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-danger)]" />
                )}
                <span className="min-w-0 flex-1 truncate">{titleOf(item.ref)}</span>
                {!item.ok && <span className="text-xs text-[var(--lumi-danger)]">{item.error}</span>}
              </li>
            ))}
          </ul>
        )}
        {errorText !== null && (
          <div role="alert" className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]">
            {errorText.title}
          </div>
        )}
      </div>
    </Dialog>
  )
}

/** F005 备注关键词过滤框（前端过滤当前列表 + 后端 note_search 列表）。 */
export function NotesSearchBox({
  onSearch,
}: {
  onSearch: (needle: string | null) => void
}) {
  const [text, setText] = useState('')
  return (
    <div className="flex items-center gap-1.5">
      <NotebookPen aria-hidden className="size-4 text-[var(--lumi-text-tertiary)]" />
      <input
        type="search"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          onSearch(e.target.value.trim() === '' ? null : e.target.value.trim())
        }}
        placeholder="按备注过滤（当前列表）"
        aria-label="按备注关键词过滤订阅"
        className="min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
      />
    </div>
  )
}
