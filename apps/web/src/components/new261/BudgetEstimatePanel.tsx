/** NEW-265 翻译任务预算预估 — 提交前的真实字数 + 本人登记单价估算：
 * 只读预检（零 provider 调用、零缓存写入）；未登记单价时诚实显示
 * estimatedCost 不可用；用户看懂量级再决定是否执行。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { estimateBudget, getBudgetSettings, putBudgetSettings, type BudgetEstimate } from '../../api/new261'
import { Button } from '../ui/Button'
import { NoticeLine } from './parts'

export function BudgetEstimatePanel({
  entryRef,
  blocks,
}: {
  entryRef: string
  blocks: Array<{ index: number; text: string }> | null
}) {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['new265-budget-settings'],
    queryFn: ({ signal }) => getBudgetSettings(signal),
  })
  const [priceInput, setPriceInput] = useState('')
  const [currencyInput, setCurrencyInput] = useState('')
  const [estimate, setEstimate] = useState<BudgetEstimate | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const saveMutation = useMutation({
    mutationFn: () => {
      const raw = priceInput.trim()
      return putBudgetSettings(raw === '' ? null : Number(raw), currencyInput.trim())
    },
    onSuccess: (settings) => {
      setNotice(settings.pricePer1kChars === null ? '已清除登记单价。' : '已登记估算单价。')
      void queryClient.invalidateQueries({ queryKey: ['new265-budget-settings'] })
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '保存失败'),
  })
  const estimateMutation = useMutation({
    mutationFn: () => estimateBudget(entryRef, blocks ?? []),
    onSuccess: (result) => {
      setEstimate(result)
      setNotice(null)
    },
    onError: (error) => {
      setEstimate(null)
      setNotice(error instanceof Error ? error.message : '预估失败')
    },
  })

  const settings = settingsQuery.data
  const hasPrice = settings !== undefined && settings.pricePer1kChars !== null

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
        <label>
          单价 / 千字符
          <input
            type="number"
            min={0}
            step="any"
            value={priceInput}
            onChange={(event) => setPriceInput(event.target.value)}
            placeholder={hasPrice && settings ? String(settings.pricePer1kChars) : '未登记'}
            aria-label="每千字符单价"
            className="ml-1 w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
        </label>
        <label>
          币种
          <input
            type="text"
            maxLength={12}
            value={currencyInput}
            onChange={(event) => setCurrencyInput(event.target.value)}
            placeholder={hasPrice && settings && settings.currency ? settings.currency : 'USD'}
            aria-label="币种"
            className="ml-1 w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
        </label>
        <Button
          size="sm"
          variant="ghost"
          disabled={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          保存单价设置
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={blocks === null || blocks.length === 0 || estimateMutation.isPending}
          onClick={() => estimateMutation.mutate()}
        >
          预估当前范围
        </Button>
      </div>

      {estimate !== null && (
        <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          <p>
            共 {estimate.totalBlocks} 段 / {estimate.totalChars} 字符；计费 {estimate.chargeableBlocks} 段 /{' '}
            {estimate.chargeableChars} 字符（缓存 {estimate.cachedBlocks} · 不翻译 {estimate.noTranslateBlocks} ·
            已有修订 {estimate.revisedBlocks} 段零费用）。
          </p>
          {estimate.estimatedCost !== null ? (
            <p className="text-[var(--lumi-text-primary)]">
              预估费用 ≈ {estimate.estimatedCost} {estimate.currency}（登记单价 {estimate.pricePer1kChars}/千字符 ·
              字数估算，非账单）。
            </p>
          ) : (
            <p className="text-[var(--lumi-text-tertiary)]">
              费用估算不可用：{estimate.note || '尚未登记单价'}。字数量级照常给出。
            </p>
          )}
        </div>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'info'}>{notice}</NoticeLine>}
    </div>
  )
}
