/** MediaBudgetPanel — NEW-355 单篇媒体流量预算面板。
 *
 * 打开大图/音频前展示已知体积与策略选择：
 * - 已知体积 = 本机附件队列对同一 URL 的历史记录；图片首开体积未知
 *   如实标注——本面板**零网络**（绝不预取测量）；
 * - 策略按单篇记忆（lib/media-budget）：只读文字 / 按次加载 / 正常
 *   加载（跟随全局）；选择即时生效于本篇（Reader 据此走既有
 *   deferImages 延后管线 / 跳过音频播放器渲染）。 */

import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { formatAttachmentBytes } from '../../lib/attachment-queue'
import {
  MEDIA_BUDGET_MODES,
  MEDIA_BUDGET_MODE_LABELS,
  estimateMediaBudget,
  readMediaBudgetDecision,
  writeMediaBudgetDecision,
  type MediaBudgetMode,
} from '../../lib/media-budget'
import { IconButton } from '../ui/IconButton'

export interface MediaBudgetPanelProps {
  entryRef: string
  /** 清洗后的正文 HTML（仅用于统计图片占位；不再发起任何请求）。 */
  contentHtml: string | null
  enclosures: Array<{ href: string; type?: string | null }>
  /** 策略变化回调（宿主据此即时执行延后管线/隐藏播放器）。 */
  onDecisionChange?: (mode: MediaBudgetMode) => void
  onClose: () => void
}

/** 统计正文中的图片 src（DOMParser 惰性解析，只读不渲染、零请求）。 */
export function collectImageSrcs(html: string | null): string[] {
  if (html === null || !html.includes('<img')) return []
  const doc = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(doc.querySelectorAll('img'))
    .map((img) => img.getAttribute('src') ?? img.getAttribute('data-lumi-src') ?? '')
    .filter((src) => src !== '')
}

export function MediaBudgetPanel({ entryRef, contentHtml, enclosures, onDecisionChange, onClose }: MediaBudgetPanelProps) {
  const [mode, setMode] = useState<MediaBudgetMode>(
    () => readMediaBudgetDecision(entryRef)?.mode ?? 'ask',
  )
  const estimate = useMemo(
    () => estimateMediaBudget({ imageSrcs: collectImageSrcs(contentHtml), enclosures }),
    [contentHtml, enclosures],
  )

  const choose = (next: MediaBudgetMode) => {
    setMode(next)
    writeMediaBudgetDecision(entryRef, next)
    onDecisionChange?.(next)
  }

  return (
    <div
      role="dialog"
      aria-label="媒体流量预算"
      data-n355-panel=""
      className="absolute right-4 top-16 z-30 max-h-[70vh] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 shadow-[var(--lumi-shadow-popover)]"
    >
      <div className="mb-2 flex items-center gap-2">
        <p className="flex-1 text-xs font-medium text-[var(--lumi-text-primary)]">
          媒体流量预算（本篇）
        </p>
        <IconButton size="sm" icon={<X aria-hidden className="size-4" />} label="关闭预算面板" touch onClick={onClose} />
      </div>

      <div className="flex flex-col gap-2" data-testid="n355-estimate">
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]" data-n355-summary="">
          图片 {estimate.imageCount} 张 · 媒体附件 {estimate.enclosureCount} 个 ·
          已知体积合计 {formatAttachmentBytes(estimate.knownTotalBytes)}
          {estimate.unknownCount > 0 && `（${estimate.unknownCount} 项体积未知）`}
        </p>
        <ul className="flex flex-col gap-1">
          {estimate.items.slice(0, 20).map((item, i) => (
            <li
              key={`${item.kind}-${i}`}
              data-n355-item=""
              className="flex items-baseline justify-between gap-2 text-xs text-[var(--lumi-text-primary)]"
            >
              <span className="min-w-0 truncate">{item.label}</span>
              <span className="shrink-0 tabular-nums text-[var(--lumi-text-secondary)]">
                {item.knownBytes === null ? '体积未知' : formatAttachmentBytes(item.knownBytes)}
              </span>
            </li>
          ))}
          {estimate.items.length === 0 && (
            <li className="text-xs text-[var(--lumi-text-tertiary)]">本篇没有图片或媒体附件。</li>
          )}
          {estimate.items.length > 20 && (
            <li className="text-xs text-[var(--lumi-text-tertiary)]">
              仅显示前 20 项（共 {estimate.items.length} 项）。
            </li>
          )}
        </ul>
        <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          已知体积仅来自本机下载记录；首开媒体不发起任何测量请求，体积未知
          如实标注。
        </p>
      </div>

      <fieldset className="mt-3 flex flex-col gap-1.5">
        <legend className="text-xs font-medium text-[var(--lumi-text-primary)]">本篇加载策略</legend>
        {MEDIA_BUDGET_MODES.map((option) => (
          <label
            key={option}
            data-n355-mode={option}
            className="flex min-h-11 cursor-pointer items-center gap-2 rounded-[var(--lumi-radius-md)] px-1.5 py-1 hover:bg-[var(--lumi-surface-hover)]"
          >
            <input
              type="radio"
              name="n355-budget-mode"
              aria-label={MEDIA_BUDGET_MODE_LABELS[option]}
              checked={mode === option}
              onChange={() => choose(option)}
              className="size-4 shrink-0 accent-[var(--lumi-accent)]"
            />
            <span className="text-xs leading-relaxed text-[var(--lumi-text-primary)]">
              {MEDIA_BUDGET_MODE_LABELS[option]}
              {option === 'ask' && mode === 'ask' && (
                <span className="ml-1 text-[var(--lumi-text-tertiary)]">（当前）</span>
              )}
            </span>
          </label>
        ))}
      </fieldset>

      {mode === 'text-only' && (
        <p role="status" data-n355-mode-note="" className="mt-2 text-xs leading-relaxed text-[var(--lumi-success)]">
          只读文字：本篇图片保持占位、音频播放器不加载；想看某个媒体时
          切回「按次加载」或「正常加载」。
        </p>
      )}
      {mode === 'per-load' && (
        <p role="status" data-n355-mode-note="" className="mt-2 text-xs leading-relaxed text-[var(--lumi-success)]">
          按次加载：图片全部占位，逐个点击「加载」才请求；音频仍需显式
          点击播放。
        </p>
      )}
    </div>
  )
}

export default MediaBudgetPanel
