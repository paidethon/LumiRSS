/** QuietHoursPanel — NEW-393 提醒静默时段设置 + 结束汇总。
 *
 * 静默只影响呈现：事件照常落库，结束后以汇总呈现窗口内未读事件
 * （真实计数），展开即收件箱原始事件。时区必须是 IANA 名称。
 */

import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  fetchQuietHours,
  fetchQuietSummary,
  putQuietHours,
} from '../../api/new391'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  inputClass,
  labelClass,
} from './parts'

export function QuietHoursPanel() {
  const [start, setStart] = useState('22:00')
  const [end, setEnd] = useState('08:00')
  const [timeZone, setTimeZone] = useState('Asia/Shanghai')
  const [error, setError] = useState('')
  const setting = useQuery({
    queryKey: ['new391', 'quiet-hours'],
    queryFn: fetchQuietHours,
  })
  const summary = useQuery({
    queryKey: ['new391', 'quiet-summary'],
    queryFn: fetchQuietSummary,
  })
  const save = useMutation({
    mutationFn: () =>
      putQuietHours({
        startHHMM: start,
        endHHMM: end,
        timeZone: timeZone.trim(),
        enabled: true,
      }),
    onSuccess: () => {
      setError('')
      void setting.refetch()
      void summary.refetch()
    },
    onError: () => setError('保存失败：时间须为 HH:MM、起止不能相同、时区须为 IANA 名称。'),
  })
  return (
    <div data-n391-panel="quiet-hours" className="flex flex-col gap-3">
      <NoteText>
        静默期间事件照常记录，只是不打扰；结束后以汇总形式呈现窗口内的未读事件。
      </NoteText>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <label className={labelClass} htmlFor="quiet-start">
            静默开始（HH:MM）
          </label>
          <input
            id="quiet-start"
            className={inputClass}
            value={start}
            onChange={(event) => setStart(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className={labelClass} htmlFor="quiet-end">
            静默结束（HH:MM，早于开始即跨午夜）
          </label>
          <input
            id="quiet-end"
            className={inputClass}
            value={end}
            onChange={(event) => setEnd(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className={labelClass} htmlFor="quiet-tz">
            时区（IANA 名称）
          </label>
          <input
            id="quiet-tz"
            className={inputClass}
            value={timeZone}
            onChange={(event) => setTimeZone(event.target.value)}
          />
        </div>
        <Button loading={save.isPending} onClick={() => save.mutate()}>
          保存静默设置
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {setting.data && (
        <NoteText>
          当前：{setting.data.enabled
            ? `已启用 ${setting.data.startHHMM}–${setting.data.endHHMM}（${setting.data.timeZone}）`
            : '未启用'}
        </NoteText>
      )}
      {summary.data && (
        <div
          data-n391-quiet-summary
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3"
        >
          <StatusLine tone={summary.data.inQuiet ? 'info' : 'ok'}>
            {summary.data.inQuiet
              ? `静默中，${summary.data.quietEndsAt ?? ''} 结束。`
              : '当前不在静默时段。'}
          </StatusLine>
          <NoteText>
            窗口内未读 {summary.data.unreadDuringWindow} 条 / 未读共{' '}
            {summary.data.unreadTotal} 条。
          </NoteText>
          <NoteText>{summary.data.note}</NoteText>
        </div>
      )}
    </div>
  )
}
