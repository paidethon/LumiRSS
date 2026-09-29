/** NEW-229 阅读约定卡 section —— 共读约定（双方独立确认）。
 *
 * 诚实边界：对方的确认状态在本部署不可见（无跨账户共享表面）——
 * 界面明示这一点，绝不伪造「对方已完成」。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  archivePact,
  confirmPact,
  createPact,
  joinPact,
  listPacts,
  type ReadingPact,
} from './api'
import { Button } from '../ui/Button'
import { Chip, ErrorNote, ItemPicker, SectionShell, useTodayItems } from './parts'

export function PactSection() {
  const qc = useQueryClient()
  const { items } = useTodayItems()
  const [ref, setRef] = useState('')
  const [deadline, setDeadline] = useState('')
  const [counterpart, setCounterpart] = useState('')
  const [joinKey, setJoinKey] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const listQuery = useQuery({
    queryKey: ['new2xx', 'pacts'],
    queryFn: ({ signal }) => listPacts(signal),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['new2xx', 'pacts'] })

  const createMutation = useMutation({
    mutationFn: () => createPact({ itemRef: ref, deadline, counterpartUsername: counterpart }),
    onSuccess: (pact) => {
      setCreatedKey(pact.pactKey)
      setRef('')
      setDeadline('')
      setCounterpart('')
      invalidate()
    },
    onError: setError,
  })
  const joinMutation = useMutation({
    mutationFn: () =>
      joinPact({
        pactKey: joinKey.trim(),
        itemRef: ref,
        deadline,
        counterpartUsername: counterpart,
      }),
    onSuccess: () => {
      setJoinKey('')
      setRef('')
      setDeadline('')
      setCounterpart('')
      invalidate()
    },
    onError: setError,
  })
  const confirmMutation = useMutation({
    mutationFn: ({ pact, confirmed }: { pact: ReadingPact; confirmed: boolean }) =>
      confirmPact(pact.id, confirmed),
    onSuccess: invalidate,
    onError: setError,
  })
  const archiveMutation = useMutation({
    mutationFn: (pact: ReadingPact) => archivePact(pact.id, true),
    onSuccess: invalidate,
    onError: setError,
  })

  const pacts = listQuery.data?.items ?? []

  return (
    <SectionShell
      title="阅读约定卡"
      hint="与一位共读成员约定同一资料和截止时间；双方各自独立确认。对方的确认状态在本部署不可见（无跨账户共享表面）——这里绝不伪造。"
    >
      <ErrorNote error={error} />
      <div className="flex flex-col gap-1.5 text-xs">
        <ItemPicker items={items} value={ref} onChange={setRef} label="资料" />
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            截止
            <input
              type="date"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
              className="min-h-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
            />
          </label>
          <label className="flex flex-col gap-0.5 text-[var(--lumi-text-secondary)]">
            对方用户名
            <input
              value={counterpart}
              onChange={(event) => setCounterpart(event.target.value)}
              className="min-h-7 w-28 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
            />
          </label>
          <Button
            size="sm"
            disabled={!ref || !deadline || !counterpart.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            发起约定
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!joinKey.trim() || !ref || !deadline || !counterpart.trim() || joinMutation.isPending}
            onClick={() => joinMutation.mutate()}
          >
            用口令加入
          </Button>
          <input
            value={joinKey}
            onChange={(event) => setJoinKey(event.target.value)}
            placeholder="约定口令（对方发你）"
            aria-label="约定口令"
            className="min-h-7 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-separator)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-xs"
          />
        </div>
        {createdKey ? (
          <p role="status" className="text-[var(--lumi-success)]">
            约定已建立。把口令发给对方（应用外交接，与邀请码同型）：
            <code className="ml-1 rounded bg-[var(--lumi-surface-hover)] px-1 py-0.5">
              {createdKey}
            </code>
          </p>
        ) : null}
      </div>

      <ul className="flex flex-col gap-1.5">
        {pacts.map((pact) => (
          <li
            key={pact.id}
            className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-separator)] px-2 py-1.5 text-xs"
          >
            <span className="font-medium text-[var(--lumi-text-primary)]">
              {pact.materialTitle ?? pact.itemRef}
            </span>
            <Chip>截止 {pact.deadline.slice(0, 10)}</Chip>
            <Chip>与 {pact.counterpartUsername}</Chip>
            {pact.myStatus === 'confirmed' ? (
              <Chip tone="accent">我已完成</Chip>
            ) : pact.myStatus === 'archived' ? (
              <Chip>已归档</Chip>
            ) : (
              <Chip tone="warn">待我确认</Chip>
            )}
            <span className="text-[var(--lumi-text-tertiary)]">对方状态不可见</span>
            <div className="ml-auto flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  confirmMutation.mutate({ pact, confirmed: pact.myStatus !== 'confirmed' })
                }
              >
                {pact.myStatus === 'confirmed' ? '撤回确认' : '我完成了'}
              </Button>
              {pact.myStatus !== 'archived' ? (
                <Button size="sm" variant="ghost" onClick={() => archiveMutation.mutate(pact)}>
                  归档
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </SectionShell>
  )
}
