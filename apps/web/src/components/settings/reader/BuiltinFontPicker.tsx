/** BuiltinFontPicker — 设置 → 阅读 → 排版「内置字体」选择器（R08）。
 *
 * 每款用自身字体渲染名称与样张（预览即所得）；样张文本触发
 * FontFaceSet 按需加载对应分片，加载中显示占位（透明度降级 + aria-busy），
 * 失败时诚实标注并回退系统同族字体。选中即写入 readerFontFamily
 * （沿用现有 portable 键），同时清空自定义字体引用（与 Aa 面板一致）。
 *
 * 键盘/语义由 components/ui 的 RadioGroup（Base UI）承担：
 * radiogroup/radio、aria-checked、方向键移动、roving tabindex。 */

import { BUILTIN_READER_FONTS, type BuiltinReaderFont } from '../../../lib/reader-style'
import { useBuiltinFontState } from '../../../lib/builtin-fonts'
import { useAppSettings } from '../../../store/app-settings'
import { RadioGroup, RadioOption } from '../../ui/RadioGroup'
import { cx } from '../../ui/cx'

/** 单个字体卡片：名称 + 定位一句话 + 自身字体样张（含加载态）。 */
function FontCard({ font }: { font: BuiltinReaderFont }) {
  const state = useBuiltinFontState(font.cssFamily, font.sample)
  const loading = state === 'loading'
  return (
    <div className="flex min-h-[44px] items-center justify-between gap-3">
      <span className="min-w-0">
        <span className="block text-sm font-medium leading-tight text-[var(--lumi-text-primary)]">
          {font.label}
        </span>
        <span className="block text-xs leading-tight text-[var(--lumi-text-secondary)]">
          {font.hint}
          {state === 'error' ? '（加载失败，回退系统字体）' : ''}
        </span>
      </span>
      <span
        aria-busy={loading}
        className={cx(
          'shrink-0 text-right text-base leading-snug text-[var(--lumi-text-primary)] transition-opacity',
          'duration-[var(--lumi-motion-fast)]',
          loading ? 'opacity-40' : 'opacity-100',
        )}
        style={{
          fontFamily: `"${font.cssFamily}", var(--lumi-font-default)`,
        }}
        data-testid={`font-sample-${font.id}`}
      >
        {font.sample}
      </span>
    </div>
  )
}

export function BuiltinFontPicker() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  return (
    <RadioGroup
      aria-label="内置字体"
      value={settings.readerFontFamily}
      onValueChange={(v) => {
        if (!(BUILTIN_READER_FONTS as readonly { id: string }[]).some((f) => f.id === v)) return
        update({ readerFontFamily: v, readerCustomFontId: null, readerFontUrl: null })
      }}
      className="flex flex-col divide-y divide-[var(--lumi-separator)]"
    >
      {BUILTIN_READER_FONTS.map((font) => (
        <RadioOption
          key={font.id}
          value={font.id}
          aria-label={`${font.label}（${font.hint}）`}
          data-testid={`font-option-${font.id}`}
          className={cx(
            'flex flex-col gap-0.5 px-2 py-2 transition-colors duration-[var(--lumi-motion-fast)]',
            'hover:bg-[var(--lumi-surface-hover)]',
            'data-checked:bg-[var(--lumi-accent-soft)]',
          )}
        >
          <FontCard font={font} />
        </RadioOption>
      ))}
    </RadioGroup>
  )
}
