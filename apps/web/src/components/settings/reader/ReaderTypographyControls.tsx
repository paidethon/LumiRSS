/** ReaderTypographyControls — 设置 → 阅读 → 排版（0017）。
 *
 * 五个连续 Slider（字号/行距/段距/正文宽度/页面边距）+ 「恢复默认」。
 * 与 Reader Aa 面板消费同一 settings store：同一数值、同一校验、同一
 * 持久化（AD-0017-2）。全部控件即时生效（WYSIWYG），无需保存按钮。 */

import { RotateCcw } from 'lucide-react'
import { useAppSettings, READER_NUMERIC_RANGES } from '../../../store/app-settings'
import { Slider } from '../../ui/Slider'
import { cx } from '../../ui/cx'

export function ReaderTypographyControls() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const resetReader = useAppSettings((s) => s.resetReader)

  const fontSize = READER_NUMERIC_RANGES.readerFontSize
  const lineHeight = READER_NUMERIC_RANGES.readerLineHeight
  const paragraphSpacing = READER_NUMERIC_RANGES.readerParagraphSpacing
  const contentWidth = READER_NUMERIC_RANGES.readerContentWidth
  const pageMargin = READER_NUMERIC_RANGES.readerPageMargin

  return (
    <div className="py-3">
      <div className="flex items-center justify-between gap-3">
        <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
          正文排版
        </label>
        <button
          type="button"
          onClick={resetReader}
          className={cx(
            'flex min-h-9 items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 text-xs text-[var(--lumi-text-secondary)]',
            'transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          恢复默认阅读设置
        </button>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        连续调节，立即生效；数值跨设备同步（服务端持久化）。
      </p>

      <div className="mt-3 flex flex-col gap-3">
        <Slider
          label="字号"
          steppers
          value={settings.readerFontSize}
          min={fontSize.min}
          max={fontSize.max}
          step={fontSize.step}
          onChange={(v) => update({ readerFontSize: v })}
          formatValue={(v) => `${v}px`}
        />
        <Slider
          label="行距"
          value={settings.readerLineHeight}
          min={lineHeight.min}
          max={lineHeight.max}
          step={lineHeight.step}
          onChange={(v) => update({ readerLineHeight: v })}
          formatValue={(v) => v.toFixed(2)}
        />
        <Slider
          label="段距"
          value={settings.readerParagraphSpacing}
          min={paragraphSpacing.min}
          max={paragraphSpacing.max}
          step={paragraphSpacing.step}
          onChange={(v) => update({ readerParagraphSpacing: v })}
          formatValue={(v) => `${v.toFixed(2)}em`}
        />
        <Slider
          label="正文宽度"
          value={settings.readerContentWidth}
          min={contentWidth.min}
          max={contentWidth.max}
          step={contentWidth.step}
          onChange={(v) => update({ readerContentWidth: v })}
          formatValue={(v) => `${v}px`}
          description="桌面端可感知；窄屏上正文自动限制在视口内（max-width 语义）。"
        />
        <Slider
          label="页面边距"
          value={settings.readerPageMargin}
          min={pageMargin.min}
          max={pageMargin.max}
          step={pageMargin.step}
          onChange={(v) => update({ readerPageMargin: v })}
          formatValue={(v) => `${v}px`}
          description="正文两侧留白；移动端自动限制在 12–20px 安全范围。"
        />
      </div>
    </div>
  )
}
