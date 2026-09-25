/** ReaderTypographyControls — 设置 → 阅读 → 排版（0017 + R5 批4）。
 *
 * 五个连续 Slider（字号/行距/段距/正文宽度/页面边距）+ F067 联动预设
 * （小/中/大一键同设字号行距）+ F065 宽度模式（固定 px / 跟随窗口
 * 百分比）+ F066「恢复默认排版」（仅排版字段，不碰其它阅读设置）。
 * 与 Reader Aa 面板消费同一 settings store：同一数值、同一校验、同一
 * 持久化（AD-0017-2）。全部控件即时生效（WYSIWYG），无需保存按钮。 */

import { RotateCcw } from 'lucide-react'
import {
  useAppSettings,
  READER_NUMERIC_RANGES,
  type ReaderContentWidthMode,
} from '../../../store/app-settings'
import {
  READER_SIZE_PRESETS,
  matchReaderSizePreset,
} from '../../../lib/reader-style'
import { Slider } from '../../ui/Slider'
import { Select } from '../../ui/Select'
import { cx } from '../../ui/cx'

/** F067：字号+行高联动预设按钮组（与单项滑杆并存；命中档高亮）。 */
function SizePresetButtons() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const matched = matchReaderSizePreset(settings.readerFontSize, settings.readerLineHeight)
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-[var(--lumi-text-primary)]">字号行距预设</span>
      <div
        role="group"
        aria-label="字号行距预设"
        className="flex overflow-hidden rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]"
      >
        {READER_SIZE_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            aria-pressed={matched?.id === preset.id}
            data-testid={`size-preset-${preset.id}`}
            onClick={() =>
              update({ readerFontSize: preset.fontSize, readerLineHeight: preset.lineHeight })
            }
            className={cx(
              'min-h-9 px-3 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              matched?.id === preset.id
                ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export function ReaderTypographyControls() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const resetReaderTypography = useAppSettings((s) => s.resetReaderTypography)

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
          onClick={resetReaderTypography}
          className={cx(
            'flex min-h-9 items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 text-xs text-[var(--lumi-text-secondary)]',
            'transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          恢复默认排版
        </button>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        连续调节，立即生效；字号/行距数值跨设备同步，宽度模式等设备本偏好仅本机生效。
      </p>

      <div className="mt-3 flex flex-col gap-3">
        {/* F067：联动预设（一键同设字号+行高；滑杆单项微调后自动去高亮） */}
        <SizePresetButtons />
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
        {/* F065：宽度模式——固定 px / 跟随窗口百分比 */}
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-[var(--lumi-text-primary)]">宽度模式</span>
          <Select
            aria-label="正文宽度模式"
            value={settings.readerContentWidthMode}
            onChange={(e) =>
              update({ readerContentWidthMode: e.target.value as ReaderContentWidthMode })
            }
            options={[
              { value: 'fixed', label: '固定宽度' },
              { value: 'viewport', label: '跟随窗口' },
            ]}
          />
        </div>
        {settings.readerContentWidthMode === 'fixed' ? (
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
        ) : (
          <Slider
            label="窗口宽度占比"
            value={settings.readerContentWidthViewport}
            min={50}
            max={100}
            step={5}
            onChange={(v) => update({ readerContentWidthViewport: v })}
            formatValue={(v) => `${Math.round(v)}%`}
            description="正文宽度跟随窗口宽度百分比（上限 100% 防溢出）。"
          />
        )}
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
