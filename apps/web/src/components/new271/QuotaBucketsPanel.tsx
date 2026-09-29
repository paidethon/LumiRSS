/** NEW-280 AI 配额分桶 — 把可用额度分到翻译/摘要/问答等用途。

- 分桶 = 对某用途设独立上限（复用既有 ai_quota 原子预占原语）；
- 快照如实显示 used/remaining/nearLimit；接近限额（≥80%）时提示
  调整分桶，而不是静默超额；
- 删除分桶 = 该用途回到「只走全局配额」。 */

import { useCallback, useEffect, useState } from 'react'
import {
  deleteQuotaBucket,
  getQuotaBuckets,
  putQuotaBucket,
  type QuotaBucketSnapshot,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

const PURPOSE_LABELS: Record<string, string> = {
  summary: '摘要',
  chat: '问答',
  translate: '翻译',
  embed: '向量',
  moderate: '审核',
  quiz: '测验',
}

export function QuotaBucketsPanel() {
  const [snapshot, setSnapshot] = useState<QuotaBucketSnapshot | null>(null)
  const [purpose, setPurpose] = useState('summary')
  const [maxCalls, setMaxCalls] = useState('5')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await getQuotaBuckets())
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function save(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await putQuotaBucket(purpose, Number(maxCalls))
      await refresh()
      setNotice(`已为「${PURPOSE_LABELS[purpose] ?? purpose}」设置分桶上限。`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(bucketPurpose: string): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await deleteQuotaBucket(bucketPurpose)
      await refresh()
      setNotice('已移除分桶；该用途回到只走全局配额。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-quota-buckets="" className="flex flex-col gap-3">
      {snapshot === null && <StatusLine tone="info">载入中…</StatusLine>}
      {snapshot !== null && (
        <>
          {snapshot.buckets.length === 0 && (
            <StatusLine tone="info">还没有分桶；所有用途只受全局配额约束。</StatusLine>
          )}
          {snapshot.buckets.map((bucket) => (
            <div key={bucket.purpose} data-new271-bucket={bucket.purpose} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              <StatusLine tone={bucket.nearLimit ? 'error' : 'info'}>
                {PURPOSE_LABELS[bucket.purpose] ?? bucket.purpose}：已用 {bucket.used} / 上限 {bucket.maxCalls}
                {bucket.nearLimit ? ' · 已接近限额，请调整分桶或减少用量（不会静默超额）' : ''}
              </StatusLine>
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void remove(bucket.purpose)}>
                移除此分桶
              </button>
            </div>
          ))}
          <div className="flex items-end gap-2 border-t border-[var(--lumi-border)] pt-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="new271-bucket-purpose" className="text-sm text-[var(--lumi-text-secondary)]">
                用途
              </label>
              <select
                id="new271-bucket-purpose"
                className={inputClass}
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
              >
                {snapshot.purposes.map((p) => (
                  <option key={p} value={p}>
                    {PURPOSE_LABELS[p] ?? p}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="new271-bucket-max" className="text-sm text-[var(--lumi-text-secondary)]">
                本窗口上限（次）
              </label>
              <input
                id="new271-bucket-max"
                type="number"
                min={1}
                className={inputClass}
                value={maxCalls}
                onChange={(e) => setMaxCalls(e.target.value)}
              />
            </div>
            <button
              type="button"
              className={buttonClass}
              disabled={busy || Number(maxCalls) < 1 || Number.isNaN(Number(maxCalls))}
              onClick={() => void save()}
            >
              设置分桶
            </button>
          </div>
          <NoteText>{snapshot.honestyNote}</NoteText>
        </>
      )}
      {notice !== '' && <StatusLine tone="ok">{notice}</StatusLine>}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
