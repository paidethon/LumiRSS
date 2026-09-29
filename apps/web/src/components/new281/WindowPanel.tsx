/** NEW-283 简报截稿窗口 — 显式时区 + 墙钟截点 + 周期；换算好的 UTC
 * 边界如实展示（未配置就说未配置，绝不编造边界）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchWindow, putWindow } from '../../api/new281'
import {
  NoteText,
  SelectField,
  StatusLine,
  TextField,
  buttonClass,
  errorText,
} from './parts'

export function WindowPanel() {
  const queryClient = useQueryClient()
  const [timezone, setTimezone] = useState('Asia/Shanghai')
  const [cutoffTime, setCutoffTime] = useState('18:00')
  const [periodDays, setPeriodDays] = useState('1')
  const [notice, setNotice] = useState<string | null>(null)

  const windowQuery = useQuery({
    queryKey: ['new281-window'],
    queryFn: ({ signal }) => fetchWindow(signal),
  })

  const saveMutation = useMutation({
    mutationFn: () => putWindow(timezone.trim(), cutoffTime.trim(), Number(periodDays)),
    onSuccess: async (window) => {
      setNotice(
        `窗口已保存：${window.timezone} ${window.cutoffTime}（${window.periodDays === 7 ? '周报' : '日报'}）；` +
          `当前窗口 ${window.startUtc} → ${window.cutoffUtc}（UTC）。`,
      )
      await queryClient.invalidateQueries({ queryKey: ['new281-window'] })
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        截稿点之后的文章属下一期（可手动调回）。时区必须显式——同一墙钟截点在不同时区是完全不同的 UTC 边界。
      </NoteText>
      {windowQuery.isError && <StatusLine tone="error">{errorText(windowQuery.error)}</StatusLine>}
      {windowQuery.data && !windowQuery.data.configured && (
        <StatusLine tone="info">尚未配置截稿窗口；生成周期简报前必须先配置。</StatusLine>
      )}
      {windowQuery.data?.configured && (
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]" data-new281-window-bounds="">
          {windowQuery.data.timezone} {windowQuery.data.cutoffTime} ·{' '}
          {windowQuery.data.periodDays === 7 ? '周报' : '日报'} · 当前窗口{' '}
          {windowQuery.data.startUtc} → {windowQuery.data.cutoffUtc}（UTC）；下一期起点 ={' '}
          {windowQuery.data.nextWindowStartUtc}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-3">
        <TextField label="时区（IANA 名称）" value={timezone} onChange={setTimezone} placeholder="Asia/Shanghai" />
        <TextField label="截稿点（当地墙钟 HH:MM）" value={cutoffTime} onChange={setCutoffTime} placeholder="18:00" />
        <SelectField
          label="周期"
          value={periodDays}
          onChange={setPeriodDays}
          options={[
            { value: '1', label: '日报（每天）' },
            { value: '7', label: '周报（每周）' },
          ]}
        />
      </div>
      <button type="button" className={buttonClass} disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
        保存截稿窗口
      </button>
      {notice && <StatusLine tone={saveMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
    </div>
  )
}
