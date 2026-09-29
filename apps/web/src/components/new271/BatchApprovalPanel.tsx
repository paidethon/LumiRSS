/** NEW-275 批量 AI 任务审批单 — 执行前清单、预算与可取消。

- 审批单 = 文章清单 + 任务类型 + 预算（最多调用数）；approve 后才可
  execute；执行逐项原子预占，预算/配额用尽即停（该项如实标注
  over_budget / quota_exceeded，剩余项保持 pending——绝不静默超额）；
- 尚未开始的项可整单取消。 */

import { useCallback, useEffect, useState } from 'react'
import {
  approveBatchApproval,
  cancelBatchApproval,
  createBatchApproval,
  executeBatchApproval,
  listBatchApprovals,
  type BatchApproval,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

const ITEM_STATUS_TEXT: Record<string, string> = {
  pending: '待执行',
  done: '完成',
  over_budget: '预算用尽（未执行）',
  quota_exceeded: '配额不足（未执行）',
  failed: '失败',
  cancelled: '已取消',
}

export function BatchApprovalPanel({ entryRef }: { entryRef: string }) {
  const [budget, setBudget] = useState('2')
  const [extraRefs, setExtraRefs] = useState('')
  const [approvals, setApprovals] = useState<BatchApproval[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setApprovals(await listBatchApprovals())
      setLoaded(true)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function create(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const refs = [entryRef, ...extraRefs.split('\n').map((line) => line.trim()).filter((line) => line !== '')]
      await createBatchApproval({ kind: 'summary', budgetCalls: Number(budget), entryRefs: refs })
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function act(fn: () => Promise<BatchApproval>): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await fn()
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-batch-approvals="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-approval-budget" className="text-sm text-[var(--lumi-text-secondary)]">
          本次预算（最多 AI 调用数，1–20）
        </label>
        <input
          id="new271-approval-budget"
          type="number"
          min={1}
          max={20}
          className={inputClass}
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-approval-refs" className="text-sm text-[var(--lumi-text-secondary)]">
          追加文章 entryRef（每行一条；当前文章已默认在清单内）
        </label>
        <textarea
          id="new271-approval-refs"
          className={inputClass}
          rows={2}
          value={extraRefs}
          onChange={(e) => setExtraRefs(e.target.value)}
        />
      </div>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void create()}>
        生成审批单（任务类型：摘要）
      </button>
      {loaded && approvals.length === 0 && <StatusLine tone="info">还没有审批单。</StatusLine>}
      {approvals.map((approval) => (
        <div key={approval.id} data-new271-approval={approval.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <StatusLine tone="info">
            摘要 · {approval.items.length} 篇 · 预算 {approval.budgetCalls} 次调用（已用{' '}
            {approval.usedCalls}）· {approval.status === 'draft' ? '待批准' : approval.status === 'approved' ? '已批准' : approval.status === 'completed' ? '已完结' : '已取消'}
          </StatusLine>
          <ul className="flex flex-col gap-0.5">
            {approval.items.map((item) => (
              <li key={item.id} className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                {item.ord + 1}. {ITEM_STATUS_TEXT[item.status] ?? item.status}
                {item.errorType !== null ? `（${item.errorType}）` : ''}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            {approval.status === 'draft' && (
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void act(() => approveBatchApproval(approval.id))}>
                批准
              </button>
            )}
            {approval.status === 'approved' && (
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void act(() => executeBatchApproval(approval.id))}>
                执行
              </button>
            )}
            {(approval.status === 'draft' || approval.status === 'approved') && (
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void act(() => cancelBatchApproval(approval.id))}>
                取消未开始项
              </button>
            )}
          </div>
        </div>
      ))}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>执行逐项预占预算与配额；预算用尽即停止，剩余项保持待执行，可先调整预算再续跑。</NoteText>
    </div>
  )
}
