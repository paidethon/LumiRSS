/** TranslationScopeBar — N087 按章节/范围翻译的选择条。
 *
 * - 翻译范围：全文（默认）/ 当前章节 / 从当前块到结尾；
 * - 预计字符量：所选块源文本长度之和（客户端可算，先看量再发车）；
 * - 派发：只把所选块送 BFF generate（有界批次顺序队列）；取消 =
 *   中止在途 fetch 且不再派发后续批次 —— 真停止请求，不只是隐藏 UI；
 * - 未选中的块绝不进入请求体（零远程调用）。
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ListTree, Send, Square } from 'lucide-react'
import {
  TRANSLATION_SCOPE_LABELS,
  TranslationQueue,
  defaultQueueSend,
  type ScopeSelection,
  type TranslationScope,
} from '../lib/translation-scope'
import { Button } from './ui/Button'

export function TranslationScopeBar({
  entryRef,
  scope,
  onScopeChange,
  computeSelection,
  disabled = false,
}: {
  entryRef: string
  scope: TranslationScope
  onScopeChange: (scope: TranslationScope) => void
  /** 选取时刻的块子集计算（含章节区间/当前块；由持有 blocks 与
   * DOM 容器的 ReaderTranslation 提供）。 */
  computeSelection: () => ScopeSelection | null
  disabled?: boolean
}) {
  const queryClient = useQueryClient()
  const [estimate, setEstimate] = useState<ScopeSelection | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const queueRef = useRef<TranslationQueue | null>(null)

  // 估计值在 effect 里算（读视口/DOM 布局不进 render）；范围或块集合
  // 变化即刷新，用户在发车前看到的量与实际发送一致。
  useEffect(() => {
    setEstimate(computeSelection())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, computeSelection])

  const dispatch = () => {
    if (busy || disabled) return
    const selected = computeSelection()
    if (selected === null || selected.blocks.length === 0) return
    setError(null)
    setBusy(true)
    const send = async (
      blocks: Array<{ index: number; text: string }>,
      signal: AbortSignal,
    ) => {
      await defaultQueueSend(entryRef)(blocks, signal)
      await queryClient.invalidateQueries({
        queryKey: ['translation-segments', entryRef],
      })
    }
    const queue = new TranslationQueue(send)
    queueRef.current = queue
    queue
      .run(selected.blocks)
      .then((result) => {
        if (!result.cancelled) setEstimate(computeSelection())
      })
      .catch(() => setError('翻译请求失败，请稍后重试。'))
      .finally(() => {
        setBusy(false)
        queueRef.current = null
      })
  }

  const cancel = () => {
    queueRef.current?.cancel()
  }

  return (
    <div
      data-lumi-translation-scope=""
      className="mb-2 flex flex-wrap items-end gap-2 text-xs"
    >
      <label className="flex items-center gap-1 text-[var(--lumi-text-secondary)]">
        <ListTree aria-hidden className="size-3.5" />
        翻译范围
        <select
          aria-label="翻译范围"
          value={scope}
          disabled={disabled}
          onChange={(e) => onScopeChange(e.target.value as TranslationScope)}
          className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
        >
          {(Object.keys(TRANSLATION_SCOPE_LABELS) as TranslationScope[]).map((key) => (
            <option key={key} value={key}>
              {TRANSLATION_SCOPE_LABELS[key]}
            </option>
          ))}
        </select>
      </label>
      {estimate !== null && (
        <span data-lumi-scope-estimate="" className="pb-1.5 text-[var(--lumi-text-tertiary)]">
          预计约 {estimate.chars} 字符 · {estimate.blocks.length} 段
        </span>
      )}
      {busy ? (
        <Button
          size="sm"
          variant="ghost"
          data-lumi-scope-cancel=""
          onClick={cancel}
        >
          <Square aria-hidden className="size-3" />
          取消
        </Button>
      ) : (
        <Button
          size="sm"
          variant="secondary"
          data-lumi-scope-dispatch=""
          disabled={disabled || estimate === null || estimate.blocks.length === 0}
          onClick={dispatch}
        >
          <Send aria-hidden className="size-3" />
          翻译所选范围
        </Button>
      )}
      {busy && (
        <span role="status" className="pb-1.5 text-[var(--lumi-text-tertiary)]">
          正在按范围翻译…
        </span>
      )}
      {error !== null && (
        <span role="alert" className="pb-1.5 text-[var(--lumi-danger)]">{error}</span>
      )}
    </div>
  )
}
