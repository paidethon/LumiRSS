/** NEW-267 专有名词保护例外 — 为当前篇登记「不保护该术语」的当前任务
 * 豁免（幂等）；命中视图显示每个例外术语命中多少个不同源段；撤销例外
 * 恢复全局默认保护。例外只影响该篇其后的新生成，既有译文原样展示。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addProtectException, getProtectExceptions, removeProtectException } from '../../api/new261'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { NoticeLine } from './parts'

const TERM_MAX = 200

export function ProtectExceptionsPanel({ entryRef }: { entryRef: string }) {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['new267-protect-exceptions', entryRef],
    queryFn: ({ signal }) => getProtectExceptions(entryRef, signal),
  })
  const [term, setTerm] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new267-protect-exceptions', entryRef] })
  }

  const addMutation = useMutation({
    mutationFn: () => addProtectException(entryRef, term.trim()),
    onSuccess: (item) => {
      setTerm('')
      setNotice(`例外已登记：「${item.term}」在这篇里其后按普通词翻译。`)
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '登记失败'),
  })
  const removeMutation = useMutation({
    mutationFn: (removeTerm: string) => removeProtectException(entryRef, removeTerm),
    onSuccess: () => {
      setNotice('例外已撤销，该术语恢复全局默认保护。')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '撤销失败'),
  })

  const exceptions = listQuery.data?.exceptions ?? []
  const hits = new Map((listQuery.data?.hits ?? []).map((hit) => [hit.term, hit.hitSegments]))

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={term}
          maxLength={TERM_MAX}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="代码符号 / 人名 / 产品名"
          aria-label="豁免术语"
          className="min-w-40 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={term.trim() === '' || addMutation.isPending}
          onClick={() => addMutation.mutate()}
        >
          登记例外
        </Button>
      </div>

      {exceptions.length === 0 && listQuery.isSuccess && (
        <EmptyState
          title="本篇没有例外"
          description="保护清单里的术语在这篇保持不翻译；需要豁免时在这里登记（只影响本篇其后新生成）。"
        />
      )}
      {exceptions.map((item) => (
        <div
          key={item.term}
          className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs"
        >
          <span className="font-medium text-[var(--lumi-text-primary)]">{item.term}</span>
          <span className="text-[var(--lumi-text-secondary)]">
            命中 {hits.get(item.term) ?? 0} 个不同源段 · 只影响其后新生成
          </span>
          <Button size="sm" variant="ghost" disabled={removeMutation.isPending} onClick={() => removeMutation.mutate(item.term)}>
            撤销例外
          </Button>
        </div>
      ))}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
