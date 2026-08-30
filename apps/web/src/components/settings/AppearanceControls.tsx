/** AccentColorPicker — 主题色选择器（0010a F1，AC10）。
 * Folo AccentColorSelector 模式（inspired）：8 预设色板 +
 * <input type="color"> 自定义取色。 */

import { useId } from 'react'
import { normalizeSettings, useAppSettings } from '../../store/app-settings'
import { prefixCustomCss, READER_BACKGROUNDS } from '../../lib/reader-style'
import { cx } from '../ui/cx'

const PRESET_ACCENTS = [
  '#6d78e8', // Lumi Mist 默认（蓝紫）
  '#5a9e6f', // 苔绿
  '#d08770', // 陶土
  '#b48ead', // 灰紫
  '#a3be8c', // 橄榄
  '#88c0d0', // 冰蓝
  '#e5c07b', // 蜜黄
  '#c678dd', // 兰紫
]

export function AccentColorPicker() {
  const accentColor = useAppSettings((s) => s.settings.accentColor)
  const update = useAppSettings((s) => s.update)
  const colorId = useId()

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        主题色
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        强调色应用于按钮、选中态与链接（全站生效）。
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2" role="radiogroup" aria-label="主题色">
        {PRESET_ACCENTS.map((hex) => (
          <button
            key={hex}
            type="button"
            role="radio"
            aria-checked={accentColor === hex}
            aria-label={`主题色 ${hex}`}
            onClick={() => update({ accentColor: hex })}
            className={cx(
              'size-7 rounded-full border-2 transition-transform duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              accentColor === hex
                ? 'scale-110 border-[var(--lumi-text-primary)]'
                : 'border-transparent hover:scale-105',
            )}
            style={{ backgroundColor: hex }}
          />
        ))}
        {/* 自定义取色 */}
        <label
          htmlFor={colorId}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-dashed border-[var(--lumi-border)] px-2 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <span
            aria-hidden
            className="size-4 rounded-full border border-[var(--lumi-border)]"
            style={{ backgroundColor: accentColor }}
          />
          自定义
          <input
            id={colorId}
            type="color"
            value={accentColor}
            onChange={(e) => update({ accentColor: e.target.value })}
            className="sr-only"
          />
        </label>
      </div>
    </div>
  )
}

/** ReaderBackgroundPicker — 阅读背景色板（0010a F6，AC16/AC17）。
 * OrigRead 色板交互复刻：预设 swatch + 「使用自定义」hex 输入 +
 * 取色器；改色自动切 custom。 */

import type { ReaderBackground } from '../../store/app-settings'

export function ReaderBackgroundPicker() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const customId = useId()

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        阅读背景
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        仅影响正文区域；浅色/深色主题各有对应色值，自定义深色背景自动切换浅色文字。
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2" role="radiogroup" aria-label="阅读背景">
        {(Object.keys(READER_BACKGROUNDS) as Exclude<ReaderBackground, 'custom'>[]).map((bg) => (
          <button
            key={bg}
            type="button"
            role="radio"
            aria-checked={settings.readerBackground === bg}
            onClick={() => update({ readerBackground: bg })}
            className={cx(
              'flex flex-col items-center gap-1 rounded-[var(--lumi-radius-md)] p-1.5 transition-colors duration-[var(--lumi-motion-fast)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              settings.readerBackground === bg
                ? 'bg-[var(--lumi-surface-selected)]'
                : 'hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            <span
              aria-hidden
              className="size-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]"
              style={{
                background:
                  bg === 'follow'
                    ? 'linear-gradient(135deg, var(--lumi-canvas) 50%, var(--lumi-surface-elevated) 50%)'
                    : READER_BACKGROUNDS[bg].light,
              }}
            />
            <span className="text-[11px] text-[var(--lumi-text-secondary)]">
              {READER_BACKGROUNDS[bg].label}
            </span>
          </button>
        ))}
        {/* 自定义色 */}
        <label
          htmlFor={customId}
          className={cx(
            'flex flex-col items-center gap-1 rounded-[var(--lumi-radius-md)] p-1.5 transition-colors duration-[var(--lumi-motion-fast)]',
            settings.readerBackground === 'custom'
              ? 'bg-[var(--lumi-surface-selected)]'
              : 'hover:bg-[var(--lumi-surface-hover)]',
          )}
        >
          <span
            aria-hidden
            className="size-7 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]"
            style={{ backgroundColor: settings.readerBackgroundCustom }}
          />
          <span className="text-[11px] text-[var(--lumi-text-secondary)]">自定义</span>
          <input
            id={customId}
            type="color"
            value={settings.readerBackgroundCustom}
            onChange={(e) =>
              // 改色自动切 custom（OrigRead 同语义）
              update({ readerBackground: 'custom', readerBackgroundCustom: e.target.value })
            }
            className="sr-only"
          />
        </label>
      </div>
      {settings.readerBackground === 'custom' && (
        <div className="mt-2 flex items-center gap-2">
          <input
            type="text"
            value={settings.readerBackgroundCustom}
            aria-label="自定义背景色 hex"
            onChange={(e) => {
              const v = e.target.value.trim()
              if (/^#[0-9a-f]{6}$/i.test(v)) update({ readerBackgroundCustom: v })
            }}
            className="w-28 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
            placeholder="#rrggbb"
          />
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            当前 {settings.readerBackgroundCustom}
          </span>
        </div>
      )}
    </div>
  )
}

/** CustomCssEditor — 自定义 CSS（0010a F7，AC14/AC22）。
 * Miniflux/CommaFeed 验证的自托管逃生舱模式（inspired）：
 * textarea + 变量提示 + 保存注入（选择器自动前缀 .lumi-reader，
 * 解析失败拒绝并提示）。 */

import { useState } from 'react'

export function CustomCssEditor() {
  const customCss = useAppSettings((s) => s.settings.customCss)
  const update = useAppSettings((s) => s.update)
  const [draft, setDraft] = useState(customCss)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // 外部变化（导入备份/重置）同步到草稿
  const [lastExternal, setLastExternal] = useState(customCss)
  if (customCss !== lastExternal) {
    setLastExternal(customCss)
    setDraft(customCss)
  }

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        自定义 CSS
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        仅作用于正文区域：选择器会自动加上 <code className="font-mono">.lumi-reader</code>{' '}
        前缀（如写 <code className="font-mono">p</code> 即{' '}
        <code className="font-mono">.lumi-reader p</code>）。可用变量：
        --lumi-reader-font-size / -line-height / -content-width 等。
      </p>
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setError(null)
          setSaved(false)
        }}
        rows={6}
        aria-label="自定义 CSS"
        spellCheck={false}
        placeholder={'p { margin-bottom: 1.2em; }\nimg { border-radius: 8px; }'}
        className="mt-2 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 font-mono text-xs leading-relaxed text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
      />
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            {
              const result = draft.trim() ? prefixCustomCss(draft) : ''
              if (result === null) {
                setError('无法解析这段 CSS（花括号不配对或空选择器）——请修正后重试')
              } else {
                update({ customCss: draft })
                setError(null)
                setSaved(true)
              }
            }
          }}
          className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 py-1.5 text-xs font-medium text-[var(--lumi-accent-contrast)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-accent-hover)]"
        >
          保存
        </button>
        <button
          type="button"
          onClick={() => {
            setDraft('')
            update({ customCss: '' })
            setError(null)
          }}
          className="rounded-[var(--lumi-radius-md)] px-3 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          清除
        </button>
        {error && <span className="text-xs text-[var(--lumi-danger)]">{error}</span>}
        {!error && saved && (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">已保存并生效</span>
        )}
      </div>
    </div>
  )
}

/** ReaderPresetPicker — 排版预设（0010a F7，AC20/AC21/AC22）。
 * 内置 5 套一键切换；用户预设可导出/导入/删除；内置可「复制派生」。 */

import { Check, Copy, Download, Trash2, Upload } from 'lucide-react'
import { BUILTIN_READER_PRESETS } from '../../lib/reader-style'
import type { ReaderPreset } from '../../store/app-settings'
import { useRef } from 'react'

export function ReaderPresetPicker() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fileRef = useRef<HTMLInputElement>(null)

  const allPresets: ReaderPreset[] = [...BUILTIN_READER_PRESETS, ...settings.readerPresets]

  /** 应用预设 = 把预设 vars 写入当前设置（AC20：一键切换）。 */
  const applyPreset = (p: ReaderPreset) => {
    update({ readerPresetId: p.id, ...p.vars })
  }

  const exportPreset = () => {
    const userPresets = settings.readerPresets
    const blob = new Blob(
      [
        JSON.stringify(
          {
            schemaVersion: 1,
            appName: 'LumiRSS',
            type: 'reader-presets',
            presets: userPresets,
          },
          null,
          2,
        ),
      ],
      { type: 'application/json' },
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `LumiRSS-reader-presets-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const importPreset = (file: File) => {
    file
      .text()
      .then((text) => {
        const data = JSON.parse(text) as { type?: string; presets?: unknown }
        if (data.type !== 'reader-presets' || !Array.isArray(data.presets))
          throw new Error('bad envelope')
        // 复用 normalize 的预设校验（通过一次临时归一化）
        const merged = normalizeSettings({
          ...useAppSettings.getState().settings,
          readerPresets: [
            ...useAppSettings.getState().settings.readerPresets,
            ...data.presets,
          ],
        })
        update({ readerPresets: merged.readerPresets })
      })
      .catch(() => {
        alert('导入失败：文件不是有效的 LumiRSS 阅读预设')
      })
  }

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        排版预设
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        一键切换一组阅读样式（字体/字号/行距/背景/对齐）。内置预设可复制派生为
        自定义预设；用户预设可导出分享。
      </p>
      <div className="mt-3 flex flex-col gap-1.5">
        {allPresets.map((p) => (
          <div
            key={p.id}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2"
          >
            <button
              type="button"
              onClick={() => applyPreset(p)}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              <span
                aria-hidden
                className={cx(
                  'flex size-4 shrink-0 items-center justify-center rounded-full border',
                  settings.readerPresetId === p.id
                    ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent)] text-[var(--lumi-accent-contrast)]'
                    : 'border-[var(--lumi-border)]',
                )}
              >
                {settings.readerPresetId === p.id && <Check aria-hidden className="size-3" />}
              </span>
              <span className="truncate text-sm text-[var(--lumi-text-primary)]">{p.name}</span>
              {!p.builtin && (
                <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                  自定义
                </span>
              )}
            </button>
            {p.builtin ? (
              <button
                type="button"
                aria-label={`从 ${p.name} 复制派生`}
                title="复制为自定义预设"
                onClick={() => {
                  const id = `user-${Date.now().toString(36)}`
                  update({
                    readerPresets: [
                      ...settings.readerPresets,
                      { id, name: `${p.name} 副本`, builtin: false, vars: { ...p.vars } },
                    ],
                  })
                }}
                className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]"
              >
                <Copy aria-hidden className="size-3.5" />
              </button>
            ) : (
              <button
                type="button"
                aria-label={`删除预设 ${p.name}`}
                onClick={() =>
                  update({
                    readerPresets: settings.readerPresets.filter((x) => x.id !== p.id),
                    ...(settings.readerPresetId === p.id ? { readerPresetId: 'default' } : {}),
                  })
                }
                className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
              >
                <Trash2 aria-hidden className="size-3.5" />
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={exportPreset}
          disabled={settings.readerPresets.length === 0}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-50"
        >
          <Download aria-hidden className="size-3.5" /> 导出预设
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <Upload aria-hidden className="size-3.5" /> 导入预设
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) importPreset(f)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
