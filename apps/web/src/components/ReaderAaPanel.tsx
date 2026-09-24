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

import { Suspense, useEffect, useState, type Ref } from 'react'
import { ALargeSmall, X } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import { formatSessionDuration } from '../lib/reader-tools'
import {
  READER_NUMERIC_RANGES,
  type ReaderBackground,
  type ReaderCaptionMode,
  type ReaderChineseConversion,
  type ReaderCodeFontSize,
  type ReaderContentWidthMode,
  type ReaderFontFamily,
  type ReaderFontWeight,
  type ReaderImageMaxWidth,
  type ReaderReadingMode,
} from '../store/app-settings'
import {
  READER_SIZE_PRESETS,
  matchReaderSizePreset,
} from '../lib/reader-style'
import { cx } from './ui/cx'
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
  paraFocusMode,
  onParaFocusModeChange,
  sessionStartedAt,
}: {
  onOpenSettings: () => void
  focusMode?: boolean
  onFocusModeChange?: (value: boolean) => void
  /** F062：逐段专注（Reader 会话级；undefined = 不渲染该开关）。 */
  paraFocusMode?: boolean
  onParaFocusModeChange?: (value: boolean) => void
  /** F080：会话起始时间戳（undefined = 不显示时长行）。 */
  sessionStartedAt?: number
}) {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const fontSize = READER_NUMERIC_RANGES.readerFontSize
  const lineHeight = READER_NUMERIC_RANGES.readerLineHeight
  const paragraphSpacing = READER_NUMERIC_RANGES.readerParagraphSpacing
  const contentWidth = READER_NUMERIC_RANGES.readerContentWidth
  const pageMargin = READER_NUMERIC_RANGES.readerPageMargin
  // F067：当前字号/行距命中的联动预设（滑杆微调后为 null = 无高亮）
  const matchedPreset = matchReaderSizePreset(settings.readerFontSize, settings.readerLineHeight)

  return (
    <div className="flex w-full flex-col gap-3" role="group" aria-label="阅读样式">
      {/* F067：字号+行高联动预设（小/中/大；与单项滑杆并存） */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-[var(--lumi-text-primary)]">预设</span>
        <div
          role="group"
          aria-label="字号行距预设"
          className="flex overflow-hidden rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]"
        >
          {READER_SIZE_PRESETS.map((preset) => (
            <button
              key={preset.id}
              type="button"
              aria-pressed={matchedPreset?.id === preset.id}
              onClick={() =>
                update({ readerFontSize: preset.fontSize, readerLineHeight: preset.lineHeight })
              }
              className={cx(
                'min-h-9 px-3 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                matchedPreset?.id === preset.id
                  ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </div>
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
      {/* F065：宽度模式（固定 px / 跟随窗口百分比；设备本） */}
      <div className={ROW}>
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
        />
      ) : (
        <Slider
          label="窗口占比"
          value={settings.readerContentWidthViewport}
          min={50}
          max={100}
          step={5}
          onChange={(v) => update({ readerContentWidthViewport: v })}
          formatValue={(v) => `${Math.round(v)}%`}
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
        {/* F15：代码自动换行 + R5 批2：F072 等宽字号档位 / F073 代码行号
            （全部设备本 settings；行号由管线按行包 span + CSS counter） */}
        <SwitchRow
          id="aa-code-wrap"
          title="代码自动换行"
          checked={settings.readerCodeWrap}
          onChange={(v) => update({ readerCodeWrap: v })}
        />
        <div className={ROW}>
          <span className="text-sm text-[var(--lumi-text-primary)]">代码字号</span>
          <Select
            aria-label="代码字号"
            value={settings.readerCodeFontSize}
            onChange={(e) => update({ readerCodeFontSize: e.target.value as ReaderCodeFontSize })}
            options={[
              { value: 's', label: '小' },
              { value: 'm', label: '中' },
              { value: 'l', label: '大' },
            ]}
          />
        </div>
        <SwitchRow
          id="aa-code-line-numbers"
          title="代码行号"
          checked={settings.readerCodeLineNumbers}
          onChange={(v) => update({ readerCodeLineNumbers: v })}
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
        {/* F062：逐段专注（会话级开关；j/k 步进、点击段聚焦、Esc 退出） */}
        {onParaFocusModeChange !== undefined && (
          <SwitchRow
            id="aa-para-focus-mode"
            title="逐段专注（J/K 步进）"
            checked={paraFocusMode ?? false}
            onChange={onParaFocusModeChange}
          />
        )}
        {/* F080：当前会话阅读时长（本次打开文章起累计；设备本计时） */}
        {sessionStartedAt !== undefined && <SessionDurationRow startedAt={sessionStartedAt} />}
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

/** F080：会话时长行——每秒刷新的「本次阅读 mm:ss」（Aa 面板打开期间
 * 才计时渲染；离开面板不累计丢失，起点 = 打开文章时刻）。 */
function SessionDurationRow({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <div className={ROW} data-lumi-session-duration="">
      <span className="text-sm text-[var(--lumi-text-primary)]">本次阅读</span>
      <output
        aria-live="off"
        className="text-sm tabular-nums text-[var(--lumi-text-secondary)]"
      >
        {formatSessionDuration(now - startedAt)}
      </output>
    </div>
  )
}

/** 入口：桌面 Popover / 移动底部 Sheet。 */
export default function ReaderAaPanel({
  focusMode,
  onFocusModeChange,
  paraFocusMode,
  onParaFocusModeChange,
  sessionStartedAt,
}: {
  /** 专注阅读当前值（Reader 持有；undefined = 不渲染该开关）。 */
  focusMode?: boolean
  /** 专注阅读切换（由 Reader 提供；undefined = 不渲染该开关）。 */
  onFocusModeChange?: (value: boolean) => void
  /** F062：逐段专注当前值（Reader 持有；undefined = 不渲染该开关）。 */
  paraFocusMode?: boolean
  /** F062：逐段专注切换（由 Reader 提供；undefined = 不渲染该开关）。 */
  onParaFocusModeChange?: (value: boolean) => void
  /** F080：会话起始时间戳（undefined = 不显示时长行）。 */
  sessionStartedAt?: number
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
              paraFocusMode={paraFocusMode}
              onParaFocusModeChange={onParaFocusModeChange}
              sessionStartedAt={sessionStartedAt}
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
              paraFocusMode={paraFocusMode}
              onParaFocusModeChange={onParaFocusModeChange}
              sessionStartedAt={sessionStartedAt}
            />
          )}
        </Popover>
      )}

      {/* 完整设置入口（响应式懒加载壳，与 SettingsButton 同模式） */}
      <SettingsShell open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  )
}
