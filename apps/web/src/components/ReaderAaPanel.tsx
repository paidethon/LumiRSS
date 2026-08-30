/** ReaderAaPanel — Reader 内快速阅读样式面板（0012 Gate 7）。
 *
 * Readwise/Instapaper Aa 菜单模式（inspired，独立实现）：
 * - 桌面 → Popover；移动 → 底部 Sheet（focus trap / Escape / safe-area）；
 * - 快速项：字体 / 字号 / 行高 / 宽度 / 背景 / 首行缩进 / 简繁 / 图片模式；
 * - 「更多阅读设置」进入完整设置（响应式壳与 SettingsButton 同模式）；
 * - 全部控件直连 useAppSettings —— 与 Settings Center 同一 settings
 *   source（AC12：禁止第二套 ReaderQuickSettingsStore）。 */

import { useEffect, useState, type Ref } from 'react'
import { ALargeSmall } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import type {
  ReaderBackground,
  ReaderChineseConversion,
  ReaderContentWidth,
  ReaderFontFamily,
  ReaderFontSize,
  ReaderImageMode,
  ReaderLineHeight,
  ReaderTextIndent,
} from '../store/app-settings'
import SettingsModal from './settings/SettingsModal'
import MobileSettingsScreen from './MobileSettingsScreen'
import { Popover } from './ui/Popover'
import { Sheet } from './ui/Sheet'
import { Select } from './ui/Select'
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

  return (
    <div className="flex w-full flex-col divide-y divide-[var(--lumi-separator)]" role="group" aria-label="阅读样式">
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
        <span className="text-sm text-[var(--lumi-text-primary)]">字号</span>
        <Select
          aria-label="正文字号"
          value={settings.readerFontSize}
          onChange={(e) => update({ readerFontSize: Number(e.target.value) as ReaderFontSize })}
          options={[
            { value: '15', label: '小' },
            { value: '17', label: '标准' },
            { value: '19', label: '大' },
            { value: '21', label: '特大' },
          ]}
        />
      </div>
      <div className={ROW}>
        <span className="text-sm text-[var(--lumi-text-primary)]">行高</span>
        <Select
          aria-label="正文行高"
          value={settings.readerLineHeight}
          onChange={(e) => update({ readerLineHeight: Number(e.target.value) as ReaderLineHeight })}
          options={[
            { value: '1.65', label: '紧凑' },
            { value: '1.85', label: '标准' },
            { value: '2.05', label: '宽松' },
          ]}
        />
      </div>
      <div className={ROW}>
        <span className="text-sm text-[var(--lumi-text-primary)]">宽度</span>
        <Select
          aria-label="正文宽度"
          value={settings.readerContentWidth}
          onChange={(e) =>
            update({ readerContentWidth: Number(e.target.value) as ReaderContentWidth })
          }
          options={[
            { value: '680', label: '窄' },
            { value: '760', label: '标准' },
            { value: '900', label: '宽' },
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
        <span className="text-sm text-[var(--lumi-text-primary)]">首行缩进</span>
        <Select
          aria-label="首行缩进"
          value={settings.readerTextIndent}
          onChange={(e) => update({ readerTextIndent: e.target.value as ReaderTextIndent })}
          options={[
            { value: 'off', label: '关闭' },
            { value: '2em', label: '2 字符' },
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
      <div className={ROW}>
        <span className="text-sm text-[var(--lumi-text-primary)]">图片</span>
        <Select
          aria-label="图片显示"
          value={settings.readerImageMode}
          onChange={(e) => update({ readerImageMode: e.target.value as ReaderImageMode })}
          options={[
            { value: 'all', label: '显示' },
            { value: 'grayscale', label: '灰度' },
            { value: 'hidden', label: '隐藏' },
          ]}
        />
      </div>
      <div className="flex min-h-11 items-center">
        <button
          type="button"
          onClick={onOpenSettings}
          className="w-full rounded-[var(--lumi-radius-md)] px-2 py-2 text-left text-sm text-[var(--lumi-accent)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          更多阅读设置…
        </button>
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
          width={280}
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
