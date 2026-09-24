/** ReaderAaPanel — Reader 内快速阅读样式面板（0012 Gate 7 / 0017 连续化）。
 *
 * Readwise/Instapaper Aa 菜单模式（inspired，独立实现）：
 * - 桌面 → Popover；移动 → 底部 Sheet（focus trap / Escape / safe-area）；
 * - 0017：字号/行高/段距/宽度/边距全部连续 Slider（微信读书式），
 *   拖动立即生效（WYSIWYG），与 Settings → 阅读 共用同一 settings
 *   store（AC12：禁止第二套 ReaderQuickSettingsStore）；
 * - 字体/背景/简繁为快捷 select；深度项在完整设置；
 * - F15/专注：代码自动换行（settings store 键）/ 专注阅读是 Reader
 *   会话级开关（Reader 持有状态，经 props 传入——settings store 无此键
 *   且禁止改 store）；N052：阅读模式（滚动/分页，设备本地键）；
 * - 「更多阅读设置」进入完整设置（响应式壳与 SettingsButton 同模式）。 */

import { Suspense, useState, type Ref } from 'react'
import { ALargeSmall, X } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import {
  READER_NUMERIC_RANGES,
  type ReaderBackground,
  type ReaderCaptionMode,
  type ReaderChineseConversion,
  type ReaderFontFamily,
  type ReaderFontWeight,
  type ReaderImageMaxWidth,
  type ReaderReadingMode,
} from '../store/app-settings'
import { useIsMobile } from '../lib/use-is-mobile'
import SettingsShell from './SettingsShell'
import { Popover } from './ui/Popover'
// bundle guard：base-ui Drawer 不进首屏 chunk——Sheet 仅移动分支且
// sheetOpen 时挂载（桌面 Popover 路径不受影响）。同步可用的 LoadedSheet
// 模式：模块预热后直接同步渲染，不走 React.lazy 的首渲染必挂起路径。
type SheetComponent = typeof import('./ui/Sheet')['Sheet']
let LoadedSheet: SheetComponent | null = null
const sheetLoad: Promise<void> = import('./ui/Sheet').then((m) => {
  LoadedSheet = m.Sheet
})
void sheetLoad

function AaSheet(props: React.ComponentProps<SheetComponent>) {
  if (LoadedSheet !== null) {
    const S = LoadedSheet
    return <S {...props} />
  }
  throw sheetLoad
}
import { Select } from './ui/Select'
import { Slider } from './ui/Slider'
import { Switch } from './ui/Switch'
import { IconButton } from './ui/IconButton'

const ROW = 'flex min-h-11 items-center justify-between gap-3'

/** 开关行：可见标题 + Switch（labelledby 关联，点击标题即可切换）。 */
function SwitchRow({
  id,
  title,
  checked,
  onChange,
}: {
  id: string
  title: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className={ROW}>
      <span id={id} className="text-sm text-[var(--lumi-text-primary)]">
        {title}
      </span>
      <Switch
        labelledby={id}
        id={`${id}-switch`}
        checked={checked}
        onCheckedChange={onChange}
        label={title}
      />
    </div>
  )
}

/** 快速控件组（Popover / Sheet 共用；同一 settings store）。 */
function AaControls({
  onOpenSettings,
  focusMode,
  onFocusModeChange,
}: {
  onOpenSettings: () => void
  focusMode?: boolean
  onFocusModeChange?: (value: boolean) => void
}) {
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
        {/* R5 批1：F068 字重 / F069 图片宽度 / F071 caption / F070 首图破格 /
            F064 纸张纹理（全部设备本设置；默认值维持既有观感） */}
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">字重</span>
          <Select
            aria-label="正文字重"
            value={String(settings.readerFontWeight)}
            onChange={(e) => update({ readerFontWeight: Number(e.target.value) as ReaderFontWeight })}
            options={[
              { value: '300', label: '细' },
              { value: '400', label: '常规' },
              { value: '500', label: '中等' },
              { value: '600', label: '半粗' },
              { value: '700', label: '粗' },
            ]}
          />
        </div>
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">图片宽度</span>
          <Select
            aria-label="图片最大宽度"
            value={settings.readerImageMaxWidth}
            onChange={(e) => update({ readerImageMaxWidth: e.target.value as ReaderImageMaxWidth })}
            options={[
              { value: '100%', label: '100%' },
              { value: '75%', label: '75%' },
              { value: '60%', label: '60%' },
            ]}
          />
        </div>
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">图片说明</span>
          <Select
            aria-label="图片说明显示"
            value={settings.readerCaptionMode}
            onChange={(e) => update({ readerCaptionMode: e.target.value as ReaderCaptionMode })}
            options={[
              { value: 'show', label: '显示' },
              { value: 'hover', label: '悬停显示' },
              { value: 'hidden', label: '隐藏' },
            ]}
          />
        </div>
        <SwitchRow
          id="aa-first-image-bleed"
          title="首图破格满宽"
          checked={settings.readerFirstImageFullBleed}
          onChange={(v) => update({ readerFirstImageFullBleed: v })}
        />
        <SwitchRow
          id="aa-paper-texture"
          title="纸张质感纹理"
          checked={settings.readerPaperTexture}
          onChange={(v) => update({ readerPaperTexture: v })}
        />
        {/* F15：代码自动换行（settings：readerCodeWrap） */}
        <SwitchRow
          id="aa-code-wrap"
          title="代码自动换行"
          checked={settings.readerCodeWrap}
          onChange={(v) => update({ readerCodeWrap: v })}
        />
        {/* N052：阅读模式（设备本地 readerReadingMode；'paged' = 分页阅读
            ——CSS 多栏横向翻页 + 点按翻页区，取代旧「按屏翻页」入口；
            旧 readerPagedMode=true 的设备经设置迁移落到分页模式） */}
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">阅读模式</span>
          <Select
            aria-label="阅读模式"
            value={settings.readerReadingMode}
            onChange={(e) =>
              update({ readerReadingMode: e.target.value as ReaderReadingMode })
            }
            options={[
              { value: 'scroll', label: '滚动' },
              { value: 'paged', label: '分页' },
            ]}
          />
        </div>
        {/* 专注阅读：Reader 会话级开关（props 传入；store 无此键） */}
        {onFocusModeChange !== undefined && (
          <SwitchRow
            id="aa-focus-mode"
            title="专注阅读"
            checked={focusMode ?? false}
            onChange={onFocusModeChange}
          />
        )}
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
export default function ReaderAaPanel({
  focusMode,
  onFocusModeChange,
}: {
  /** 专注阅读当前值（Reader 持有；undefined = 不渲染该开关）。 */
  focusMode?: boolean
  /** 专注阅读切换（由 Reader 提供；undefined = 不渲染该开关）。 */
  onFocusModeChange?: (value: boolean) => void
} = {}) {
  const isMobile = useIsMobile()
  const [sheetOpen, setSheetOpen] = useState(false)
  // 完整设置入口的状态挂在本组件（避免 Popover/Sheet 卸载时丢失）
  const [settingsOpen, setSettingsOpen] = useState(false)

  const openSettings = () => {
    setSheetOpen(false)
    setSettingsOpen(true)
  }

  const trigger = (
    extra: {
      onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void
      'aria-expanded'?: boolean
      ref?: Ref<HTMLButtonElement>
    } = {},
  ) => (
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
          {sheetOpen && (
          <Suspense fallback={null}>
          <AaSheet
            open={sheetOpen}
            onClose={() => setSheetOpen(false)}
            label="阅读样式"
            side="bottom"
            panelClassName="px-4 pb-[max(1rem,var(--safe-bottom))] pt-2"
          >
            <div className="mb-1 flex items-center justify-between">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">阅读样式</p>
              <IconButton
                size="lg"
                icon={<X aria-hidden className="size-4" />}
                label="关闭"
                onClick={() => setSheetOpen(false)}
              />
            </div>
            <AaControls
              onOpenSettings={openSettings}
              focusMode={focusMode}
              onFocusModeChange={onFocusModeChange}
            />
          </AaSheet>
          </Suspense>
          )}
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
          {() => (
            <AaControls
              onOpenSettings={openSettings}
              focusMode={focusMode}
              onFocusModeChange={onFocusModeChange}
            />
          )}
        </Popover>
      )}

      {/* 完整设置入口（响应式懒加载壳，与 SettingsButton 同模式） */}
      <SettingsShell open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}
