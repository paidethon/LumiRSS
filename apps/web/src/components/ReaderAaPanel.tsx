/** ReaderAaPanel — Reader 内快速阅读样式面板（0012 Gate 7 / 0017 连续化）。
 *
 * Readwise/Instapaper Aa 菜单模式（inspired，独立实现）：
 * - 桌面 → Popover；移动 → 底部 Sheet（focus trap / Escape / safe-area）；
 * - 0017：字号/行高/段距/宽度/边距全部连续 Slider（微信读书式），
 *   拖动立即生效（WYSIWYG），与 Settings → 阅读 共用同一 settings
 *   store（AC12：禁止第二套 ReaderQuickSettingsStore）；
 * - 字体/背景/简繁为快捷 select；深度项在完整设置；
 * - 「更多阅读设置」进入完整设置（响应式壳与 SettingsButton 同模式）。 */

import { useEffect, useState, type Ref } from 'react'
import { ALargeSmall } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import {
  READER_NUMERIC_RANGES,
  type ReaderBackground,
  type ReaderChineseConversion,
  type ReaderFontFamily,
} from '../store/app-settings'
import SettingsModal from './settings/SettingsModal'
import MobileSettingsScreen from './MobileSettingsScreen'
import { Popover } from './ui/Popover'
import { Sheet } from './ui/Sheet'
import { Select } from './ui/Select'
import { Slider } from './ui/Slider'
import { IconButton } from './ui/IconButton'

/** 移动断点检测（<768px → Sheet；面板行为随容器自适应）。 */
function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(
    () => typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 767px)').matches,
  )
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(max-width: 767px)')
    const onChange = (e: MediaQueryListEvent) => setMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

const ROW = 'flex min-h-11 items-center justify-between gap-3'

/** 快速控件组（Popover / Sheet 共用；同一 settings store）。 */
function AaControls({ onOpenSettings }: { onOpenSettings: () => void }) {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const fontSize = READER_NUMERIC_RANGES.readerFontSize
  const lineHeight = READER_NUMERIC_RANGES.readerLineHeight
  const paragraphSpacing = READER_NUMERIC_RANGES.readerParagraphSpacing
  const contentWidth = READER_NUMERIC_RANGES.readerContentWidth
  const pageMargin = READER_NUMERIC_RANGES.readerPageMargin

  return (
    <div className="flex w-full flex-col gap-3" role="group" aria-label="阅读样式">
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
      />
      <Slider
        label="页面边距"
        value={settings.readerPageMargin}
        min={pageMargin.min}
        max={pageMargin.max}
        step={pageMargin.step}
        onChange={(v) => update({ readerPageMargin: v })}
        formatValue={(v) => `${v}px`}
      />

      <div className="mt-1 flex w-full flex-col divide-y divide-[var(--lumi-separator)] border-t border-[var(--lumi-separator)]">
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">字体</span>
          <Select
            aria-label="正文字体"
            value={settings.readerFontFamily}
            onChange={(e) =>
              update({
                readerFontFamily: e.target.value as ReaderFontFamily,
                readerCustomFontId: null,
                readerFontUrl: null,
              })
            }
            options={[
              { value: 'system', label: '默认' },
              { value: 'sans', label: '无衬线' },
              { value: 'serif', label: '衬线' },
              { value: 'mono', label: '等宽' },
            ]}
          />
        </div>
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">背景</span>
          <Select
            aria-label="阅读背景"
            value={settings.readerBackground}
            onChange={(e) => update({ readerBackground: e.target.value as ReaderBackground })}
            options={[
              { value: 'follow', label: '跟随主题' },
              { value: 'paper', label: '纸白' },
              { value: 'warm', label: '暖白' },
              { value: 'sepia', label: '米黄' },
              { value: 'mint', label: '淡绿' },
              { value: 'custom', label: '自定义' },
            ]}
          />
        </div>
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">简繁</span>
          <Select
            aria-label="简繁转换"
            value={settings.readerChineseConversion}
            onChange={(e) =>
              update({ readerChineseConversion: e.target.value as ReaderChineseConversion })
            }
            options={[
              { value: 'off', label: '原文' },
              { value: 's2t', label: '简 → 繁' },
              { value: 't2s', label: '繁 → 简' },
              { value: 'tw', label: '繁（台）' },
              { value: 'hk', label: '繁（港）' },
            ]}
          />
        </div>
        <div className="flex min-h-11 items-center">
          <button
            type="button"
            onClick={onOpenSettings}
            className="w-full rounded-[var(--lumi-radius-md)] px-2 py-2 text-left text-sm text-[var(--lumi-accent-text)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
          >
            更多阅读设置…
          </button>
        </div>
      </div>
    </div>
  )
}

/** 入口：桌面 Popover / 移动底部 Sheet。 */
export default function ReaderAaPanel() {
  const isMobile = useIsMobile()
  const [sheetOpen, setSheetOpen] = useState(false)
  // 完整设置入口的状态挂在本组件（避免 Popover/Sheet 卸载时丢失）
  const [settingsOpen, setSettingsOpen] = useState(false)

  const openSettings = () => {
    setSheetOpen(false)
    setSettingsOpen(true)
  }

  const trigger = (extra: { onClick?: () => void; 'aria-expanded'?: boolean; ref?: Ref<HTMLButtonElement> } = {}) => (
    <IconButton
      icon={<ALargeSmall aria-hidden className="size-4" />}
      label="阅读样式"
      touch
      aria-haspopup="dialog"
      {...extra}
    />
  )

  return (
    <>
      {isMobile ? (
        <>
          {trigger({ onClick: () => setSheetOpen(true) })}
          <Sheet
            open={sheetOpen}
            onClose={() => setSheetOpen(false)}
            label="阅读样式"
            side="bottom"
            panelClassName="px-4 pb-[max(1rem,var(--safe-bottom))] pt-2"
          >
            <div className="mb-1 flex items-center justify-between">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">阅读样式</p>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                className="flex size-11 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
              >
                <span aria-hidden>✕</span>
                <span className="sr-only">关闭</span>
              </button>
            </div>
            <AaControls onOpenSettings={openSettings} />
          </Sheet>
        </>
      ) : (
        <Popover
          width={320}
          trigger={({ triggerProps }) =>
            trigger({
              onClick: triggerProps.onClick,
              'aria-expanded': triggerProps['aria-expanded'],
              ref: triggerProps.ref as Ref<HTMLButtonElement>,
            })
          }
        >
          {() => <AaControls onOpenSettings={openSettings} />}
        </Popover>
      )}

      {/* 完整设置入口（响应式壳，与 SettingsButton 同模式） */}
      <div className="hidden max-md:contents">
        <MobileSettingsScreen open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
      <div className="contents max-md:hidden">
        <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </>
  )
}
