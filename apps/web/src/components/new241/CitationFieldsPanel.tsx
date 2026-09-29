/** NEW-245 引文出处补全 — 登记个人引用（原始值），逐项补充 author/date，
 * 生效值三分：原始 / 用户补充；撤销补充不改动原始值。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  deleteCitationSupplement,
  listCitations,
  putCitationSupplement,
  registerCitation,
  type CitationFieldView,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

function FieldRow({ name, field }: { name: string; field: CitationFieldView }) {
  return (
    <span>
      {name}：
      {field.origin === 'supplement' ? (
        <>原始（空）→ 用户补充「{field.effective}」</>
      ) : field.origin === 'original' ? (
        <>原始「{field.effective}」</>
      ) : (
        '缺失'
      )}
    </span>
  )
}

export function CitationFieldsPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const [newRef, setNewRef] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newAuthor, setNewAuthor] = useState('')
  const [newDate, setNewDate] = useState('')
  const [targetRef, setTargetRef] = useState('')
  const [authorSupplement, setAuthorSupplement] = useState('')
  const [dateSupplement, setDateSupplement] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const citations = useQuery({
    queryKey: ['new245-citations'],
    queryFn: ({ signal }) => listCitations(signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new245-citations'] })
  }

  const registerMutation = useMutation({
    mutationFn: () =>
      registerCitation(
        newRef,
        newTitle,
        newAuthor.trim() === '' ? null : newAuthor,
        newDate.trim() === '' ? null : newDate,
      ),
    onSuccess: async () => {
      setNotice('引用已登记（原始值）。')
      setNewRef('')
      setNewTitle('')
      setNewAuthor('')
      setNewDate('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })

  const supplementMutation = useMutation({
    mutationFn: async () => {
      if (authorSupplement.trim() !== '') {
        await putCitationSupplement(targetRef, 'author', authorSupplement)
      }
      if (dateSupplement.trim() !== '') {
        await putCitationSupplement(targetRef, 'date', dateSupplement)
      }
    },
    onSuccess: async () => {
      setNotice('补充已保存（原始值保留）。')
      setAuthorSupplement('')
      setDateSupplement('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '补充失败'),
  })

  const revertMutation = useMutation({
    mutationFn: async () => {
      await deleteCitationSupplement(targetRef, 'author')
      await deleteCitationSupplement(targetRef, 'date')
    },
    onSuccess: async () => {
      setNotice('补充已撤销，原始值不变。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '撤销失败'),
  })

  const items = citations.data?.items ?? []

  return (
    <section
      aria-label="引文出处补全（NEW-245）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">引文出处补全</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-245</span>
      </div>

      <div className="flex flex-col gap-1">
        <input
          aria-label="新引用 ref"
          value={newRef}
          onChange={(event) => setNewRef(event.target.value)}
          placeholder={`引用 ref（可填 ${entryRef ? '当前文章 ref' : '资料 ref'}）`}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <input
          aria-label="新引用标题"
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          placeholder="标题"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <div className="flex gap-1">
          <input
            aria-label="新引用作者（可空）"
            value={newAuthor}
            onChange={(event) => setNewAuthor(event.target.value)}
            placeholder="作者（可空，稍后补充）"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <input
            aria-label="新引用日期（可空）"
            value={newDate}
            onChange={(event) => setNewDate(event.target.value)}
            placeholder="日期（可空）"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
        </div>
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={newRef.trim() === '' || newTitle.trim() === '' || registerMutation.isPending}
          onClick={() => registerMutation.mutate()}
        >
          登记引用
        </Button>
      </div>

      {citations.isPending && <Skeleton className="h-12 w-full" />}
      {citations.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
          引用列表加载失败。{citations.error instanceof Error ? citations.error.message : ''}
        </div>
      )}
      {!citations.isPending && items.length === 0 && !citations.isError && (
        <EmptyState title="还没有登记过引用" description="登记后可逐项补充缺失的作者或日期。" />
      )}
      {items.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {items.map((item) => (
            <li key={item.citationRef}>
              <span className="text-[var(--lumi-text-primary)]">{item.title}</span>（{item.citationRef}）
              <FieldRow name="作者" field={item.author} />；<FieldRow name="日期" field={item.date} />
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 && (
        <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            补充目标
            <select
              aria-label="选择要补充的引用"
              value={targetRef}
              onChange={(event) => setTargetRef(event.target.value)}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              <option value="">选择引用…</option>
              {items.map((item) => (
                <option key={item.citationRef} value={item.citationRef}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-1">
            <input
              aria-label="补充作者"
              value={authorSupplement}
              onChange={(event) => setAuthorSupplement(event.target.value)}
              placeholder="补充作者（留空不动）"
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            />
            <input
              aria-label="补充日期"
              value={dateSupplement}
              onChange={(event) => setDateSupplement(event.target.value)}
              placeholder="补充日期（留空不动）"
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            />
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={targetRef === '' || supplementMutation.isPending}
              onClick={() => supplementMutation.mutate()}
            >
              保存补充
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={targetRef === '' || revertMutation.isPending}
              onClick={() => revertMutation.mutate()}
            >
              撤销补充
            </Button>
          </div>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
