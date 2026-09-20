/** AiQuotaCard — F064 AI 用量限制（设置 → AI 区）。
 *
 * - 窗口（不限/每天/每月）+ 上限（0 = 不限，1..10000）；
 * - 当前窗口已用/剩余/重置时间（GET /settings/ai/quota，服务端本地
 *   时区口径，诚实展示）；
 * - 保存立即生效（服务端每次调用前实时读取配置）。 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { getAiQuota, updateAiSettings } from '../../api/client'
import { dateTimeFormatter } from '../../lib/date-format'
import { Button } from '../ui/Button'

export function AiQuotaCard() {
  const queryClient = useQueryClient()
  const usageQuery = useQuery({
    queryKey: ['ai-quota'],
    queryFn: getAiQuota,
    staleTime: 15_000,
  })
  const [window, setWindow] = useState<'' | 'day' | 'month'>('')
  const [maxCalls, setMaxCalls] = useState<number>(0)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const usage = usageQuery.data
    if (usage !== undefined) {
      setWindow(usage.window)
      setMaxCalls(usage.maxCalls)
    }
  }, [usageQuery.data])

  const save = useMutation({
    mutationFn: () =>
      updateAiSettings({ quotaWindow: window, quotaMaxCalls: maxCalls } as Parameters<
        typeof updateAiSettings
      >[0]),
    onSuccess: async () => {
      setSaved(true)
      await queryClient.invalidateQueries({ queryKey: ['ai-quota'] })
      await queryClient.invalidateQueries({ queryKey: ['ai-settings'] })
    },
  })

  const usage = usageQuery.data
  const unlimited = window === '' || maxCalls === 0

  return (
    <section
      data-lumi-ai-quota=""
      aria-label="用量限制"
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4"
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
        <Gauge aria-hidden className="size-4" />
        用量限制
      </h3>
      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
        按 AI 生成请求（摘要/翻译/对话等）事前拦截：达到上限后本窗口内不再发起任何
        AI 请求（上游零请求），窗口按服务器本地时间滚动。
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          计数窗口
          <select
            aria-label="计数窗口"
            value={window}
            onChange={(e) => setWindow(e.target.value as '' | 'day' | 'month')}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm"
          >
            <option value="">不限</option>
            <option value="day">每天</option>
            <option value="month">每月</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          请求上限（0 = 不限）
          <input
            aria-label="请求上限"
            type="number"
            min={0}
            max={10000}
            value={maxCalls}
            disabled={window === ''}
            onChange={(e) =>
              setMaxCalls(e.target.value === '' ? 0 : Math.max(0, Math.min(10000, Number(e.target.value))))
            }
            className="w-28 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm disabled:opacity-60"
          />
        </label>
        <Button
          size="sm"
          variant="primary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? '保存中…' : '保存用量限制'}
        </Button>
      </div>
      {/* 用量（诚实口径：未配置 = 不显示已用/剩余） */}
      {usage !== undefined && !unlimited && (
        <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]" aria-live="polite">
          本窗口已用 {usage.used} / 上限 {usage.maxCalls}
          {usage.remaining > 0 ? `（剩余 ${usage.remaining}）` : '（已用尽）'}
          ，重置于 {dateTimeFormatter.format(Date.parse(usage.windowReset))}
        </p>
      )}
      {unlimited && (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">未配置限制，不拦截 AI 请求。</p>
      )}
      {saved && !save.isPending && !save.isError && (
        <p role="status" className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          已保存，立即生效。
        </p>
      )}
      {save.isError && (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          保存失败，请稍后重试。
        </p>
      )}
    </section>
  )
}
