/** AccentColorPicker — 主题色选择器（0010a F1，AC10）。
 * Folo AccentColorSelector 模式（inspired）：8 预设色板 +
 * <input type="color"> 自定义取色。 */

import { useId } from 'react'
import { normalizeSettings, useAppSettings } from '../../store/app-settings'
import { prefixCustomCss, READER_BACKGROUNDS } from '../../lib/reader-style'
import {
  BG_IMAGE_OVERLAY_MAX,
  BG_IMAGE_OVERLAY_MIN,
  processBackgroundImageFile,
} from '../../lib/reader-bg-image'
import { Image as ImageIcon } from 'lucide-react'
import { Slider } from '../ui/Slider'
import {
  backupCurrentCustomCss,
  loadBackupCustomCss,
  validateCustomCss,
} from '../../lib/custom-css'
import { RadioGroup, RadioOption } from '../ui/RadioGroup'
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
      <RadioGroup
        aria-label="主题色"
        value={accentColor}
        onValueChange={(hex) => update({ accentColor: hex })}
        className="mt-3 flex flex-wrap items-center gap-2"
      >
        {PRESET_ACCENTS.map((hex) => (
          <RadioOption
            key={hex}
            value={hex}
            aria-label={`主题色 ${hex}`}
            className={cx(
              'size-7 rounded-full border-2 transition-transform duration-[var(--lumi-motion-fast)]',
              'data-checked:scale-110 data-checked:border-[var(--lumi-text-primary)]',
              'border-transparent hover:scale-105',
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
      </RadioGroup>
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
      <RadioGroup
        aria-label="阅读背景"
        value={settings.readerBackground}
        onValueChange={(bg) => update({ readerBackground: bg })}
        className="mt-3 flex flex-wrap items-center gap-2"
      >
        {(Object.keys(READER_BACKGROUNDS) as Exclude<ReaderBackground, 'custom'>[]).map((bg) => (
          <RadioOption
            key={bg}
            value={bg}
            className={cx(
              'flex flex-col items-center gap-1 rounded-[var(--lumi-radius-md)] p-1.5 transition-colors duration-[var(--lumi-motion-fast)]',
              'data-checked:bg-[var(--lumi-surface-selected)] data-not-checked:hover:bg-[var(--lumi-surface-hover)]',
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
          </RadioOption>
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
      </RadioGroup>
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
      <ReaderBackgroundImageSection />
    </div>
  )
}

/** ReaderBackgroundImageSection — P14 背景图片（设备本地、隐私优先）。
 * 本机图片 → canvas 降采样重编码（≤2MB data URL，lib/reader-bg-image）→
 * 可读性检查给出建议遮罩与提示；图片以 data URL 存 settings 键
 * readerBackgroundImage（设备本地，绝不进 PORTABLE_KEYS），全程零网络。
 * 遮罩不透明度 0–80%（默认 40%），用户可调并持久化。 */
function ReaderBackgroundImageSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hint, setHint] = useState<string | null>(null)

  const hasImage = settings.readerBackgroundImage !== null

  const handleFile = (file: File) => {
    setBusy(true)
    setError(null)
    setHint(null)
    void processBackgroundImageFile(file).then((result) => {
      setBusy(false)
      if (!result.ok) {
        setError(result.error)
        return
      }
      // 可读性检查：直接应用建议遮罩（用户可随后用 slider 微调）
      update({
        readerBackgroundImage: result.dataUrl,
        readerBackgroundImageOverlay: result.recommendedOverlay,
      })
      setHint(result.hint.text)
    })
  }

  return (
    <div className="mt-3 border-t border-[var(--lumi-separator)] pt-3">
      <label
        htmlFor="reader-bg-image-file"
        className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]"
      >
        背景图片
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        以本机图片作为阅读背景。图片仅保存在本设备浏览器中，不会上传到任何服务器；
        自动压缩到 2MB 以内并给出遮罩建议。
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ImageIcon aria-hidden className="size-3.5" />
          {hasImage ? '更换图片…' : '选择图片…'}
        </button>
        {hasImage && (
          <button
            type="button"
            onClick={() => {
              update({ readerBackgroundImage: null })
              setHint(null)
              setError(null)
            }}
            className="rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
          >
            移除图片
          </button>
        )}
        <input
          ref={fileRef}
          id="reader-bg-image-file"
          type="file"
          accept="image/*"
          aria-label="选择背景图片"
          className="sr-only"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleFile(f)
            e.target.value = ''
          }}
        />
      </div>
      {busy && (
        <p role="status" className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          正在本地处理图片…
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs leading-relaxed text-[var(--lumi-danger)]">
          {error}
        </p>
      )}
      {!busy && hint !== null && (
        <p role="status" className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          {hint}
        </p>
      )}
      {hasImage && (
        <div className="mt-3">
          <Slider
            label="图片遮罩不透明度"
            min={BG_IMAGE_OVERLAY_MIN}
            max={BG_IMAGE_OVERLAY_MAX}
            step={5}
            value={settings.readerBackgroundImageOverlay}
            onChange={(v) => update({ readerBackgroundImageOverlay: v })}
            formatValue={(v) => `${v}%`}
            description="图片上的遮罩强度：越高越接近纯色背景，文字越清晰。"
          />
        </div>
      )}
    </div>
  )
}

/** CustomCssEditor — 自定义 CSS（0010a F7，AC14/AC22；F112 收尾）。
 * Miniflux/CommaFeed 验证的自托管逃生舱模式（inspired）：
 * textarea + 变量提示 + 保存注入（选择器自动前缀 .lumi-reader，
 * 解析失败拒绝并提示）。
 * F112：实时预览沙盒（隔离 class 命名空间 + 示例文章复刻）、
 * @import/绝对 url() 拦截（白名单仅相对/#）、上一有效版本恢复
 * （备份键 lumirss-custom-css-last-valid，device-local）。 */

export function CustomCssEditor() {
  const customCss = useAppSettings((s) => s.settings.customCss)
  const update = useAppSettings((s) => s.update)
  const [draft, setDraft] = useState(customCss)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [backup, setBackup] = useState<string | null>(() => loadBackupCustomCss(customCss))

  // 外部变化（导入备份/重置）同步到草稿
  const [lastExternal, setLastExternal] = useState(customCss)
  if (customCss !== lastExternal) {
    setLastExternal(customCss)
    setDraft(customCss)
  }

  // F112：预览沙盒——同一段前缀化 CSS 只作用于沙盒内的示例文章
  //（.lumi-reader 命名空间隔离，样式不逃逸到设置页）。
  const previewCss = draft.trim() !== '' ? prefixCustomCss(draft) : null
  const draftValid = previewCss !== null

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
        @import 与绝对 url() 会被拦截（白名单：相对路径 / # 片段）。
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
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            const problem = validateCustomCss(draft)
            if (problem !== null) {
              setError(problem)
              setSaved(false)
              return
            }
            // 成功保存前备份「当前生效值」——出问题可一键恢复
            if (customCss !== draft) backupCurrentCustomCss(customCss)
            update({ customCss: draft })
            setError(null)
            setSaved(true)
            setBackup(loadBackupCustomCss(draft))
          }}
          className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 py-1.5 text-xs font-medium text-[var(--lumi-accent-contrast)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-accent-hover)]"
        >
          保存
        </button>
        <button
          type="button"
          data-css-preview-toggle=""
          aria-pressed={previewOpen}
          onClick={() => setPreviewOpen((v) => !v)}
          className="rounded-[var(--lumi-radius-md)] px-3 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          {previewOpen ? '隐藏预览' : '预览'}
        </button>
        {backup !== null && (
          <button
            type="button"
            data-css-restore-backup=""
            onClick={() => {
              setDraft(backup)
              update({ customCss: backup })
              setError(null)
              setSaved(true)
              setBackup(loadBackupCustomCss(backup))
            }}
            className="rounded-[var(--lumi-radius-md)] px-3 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
          >
            恢复上一有效版本
          </button>
        )}
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
        {error && (
          <span className="text-xs text-[var(--lumi-danger)]" role="alert" data-css-error="">
            {error}
          </span>
        )}
        {!error && saved && (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">已保存并生效</span>
        )}
      </div>

      {/* F112 预览沙盒：示例文章复刻 + 草稿 CSS（前缀化后仅命中沙盒）。
          非法草稿不渲染样式（避免半解析产物逃逸）。 */}
      {previewOpen ? (
        <div className="mt-2" data-css-preview-sandbox="">
          {!draftValid && draft.trim() !== '' ? (
            <p className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs text-[var(--lumi-text-tertiary)]">
              当前草稿无法解析——预览不可用。
            </p>
          ) : (
            <>
              {previewCss !== null && <style>{previewCss}</style>}
              <div className="lumi-reader rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
                <h2 className="text-base font-semibold">示例文章：深空里的信标</h2>
                <p className="mt-1 text-sm leading-relaxed">
                  这是一段示例正文，用于预览自定义 CSS 的实际效果——字号、行高、
                  边距与圆角都会在这里如实呈现。
                </p>
                <p className="mt-1 text-sm">
                  <a href="#" onClick={(event) => event.preventDefault()}>
                    一个示例链接
                  </a>{' '}
                  与 <code className="font-mono text-xs">行内代码</code>。
                </p>
                <blockquote className="mt-2 border-l-2 border-[var(--lumi-border)] pl-2 text-sm text-[var(--lumi-text-secondary)]">
                  引用块：检查缩进与颜色是否如预期。
                </blockquote>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}

/** ReaderPresetPicker — 排版预设（0010a F7，AC20/AC21/AC22）。
 * 内置 5 套一键切换；用户预设可导出/导入/删除；内置可「复制派生」。
 * F036 收尾：预设编辑器暴露 宽度/栏数/设备适用（lib/reader-preset-device
 * 的 v2 逻辑），desktop-only 预设移动端应用时诚实标注「桌面端生效」。 */

import { Check, Copy, Download, Trash2, Upload } from 'lucide-react'
import { BUILTIN_READER_PRESETS } from '../../lib/reader-style'
import type { AppSettings, ReaderPreset } from '../../store/app-settings'
import { READER_NUMERIC_RANGES } from '../../store/app-settings'
import { applyPresetForDevice, type PresetVarsV2 } from '../../lib/reader-preset-device'
import { useIsMobile } from '../../lib/use-is-mobile'
import { useRef, useState } from 'react'

export function ReaderPresetPicker() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fileRef = useRef<HTMLInputElement>(null)
  const isMobile = useIsMobile()
  const [deviceNotice, setDeviceNotice] = useState<string | null>(null)

  const allPresets: ReaderPreset[] = [...BUILTIN_READER_PRESETS, ...settings.readerPresets]
  const selected = allPresets.find((p) => p.id === settings.readerPresetId) ?? null

  /** 应用预设 = 把预设 vars 写入当前设置（AC20：一键切换）。
   * F036：经 applyPresetForDevice —— 移动端应用 desktop-only 预设时
   * 忽略宽度/栏数并诚实标注「桌面端生效」。 */
  const applyPreset = (p: ReaderPreset) => {
    const result = applyPresetForDevice(p.vars as PresetVarsV2, isMobile)
    const v = result.vars
    const patch: Partial<AppSettings> = { readerPresetId: p.id }
    if (v.readerFontFamily !== undefined) {
      patch.readerFontFamily = v.readerFontFamily as AppSettings['readerFontFamily']
    }
    if (v.readerFontSize !== undefined) patch.readerFontSize = Number(v.readerFontSize)
    if (v.readerLineHeight !== undefined) patch.readerLineHeight = Number(v.readerLineHeight)
    if (v.readerBackground !== undefined) {
      patch.readerBackground = v.readerBackground as AppSettings['readerBackground']
    }
    if (v.readerParagraphSpacing !== undefined) {
      patch.readerParagraphSpacing = Number(v.readerParagraphSpacing)
    }
    if (typeof v.readerJustify === 'boolean') patch.readerJustify = v.readerJustify
    if (v.readerContentWidth !== undefined) patch.readerContentWidth = v.readerContentWidth
    update(patch)
    setDeviceNotice(result.notice)
  }

  /** 编辑当前用户预设的 v2 字段（内置只读——复制派生后可编辑）。 */
  const editSelectedVars = (patch: Partial<ReaderPreset['vars']>) => {
    if (selected === null || selected.builtin) return
    update({
      readerPresets: settings.readerPresets.map((p) =>
        p.id === selected.id ? { ...p, vars: { ...p.vars, ...patch } } : p,
      ),
    })
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
      {deviceNotice && (
        <p role="status" className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          {deviceNotice}
        </p>
      )}
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
      <PresetLayoutEditor
        selected={selected}
        onEdit={editSelectedVars}
      />
    </div>
  )
}

/** F036 预设编辑器：宽度 / 栏数 / 设备适用（v2 字段）。
 * 仅用户预设可编辑（内置只读，提示先复制派生）；desktop-only
 * 附「桌面端生效」诚实标注。 */
function PresetLayoutEditor({
  selected,
  onEdit,
}: {
  selected: ReaderPreset | null
  onEdit: (patch: Partial<ReaderPreset['vars']>) => void
}) {
  if (selected === null) return null
  const width = READER_NUMERIC_RANGES.readerContentWidth
  if (selected.builtin) {
    return (
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        内置预设只读——「复制为自定义预设」后可编辑布局宽度、栏数与设备适用。
      </p>
    )
  }
  const scope = selected.vars.deviceScope === 'desktop' ? 'desktop' : 'all'
  const columns = selected.vars.readerColumns ?? 1
  return (
    <div className="mt-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
      <p className="text-xs font-medium text-[var(--lumi-text-primary)]">
        预设布局（{selected.name}）
      </p>
      <label
        htmlFor="preset-width-range"
        className="mt-3 flex items-center justify-between text-xs text-[var(--lumi-text-secondary)]"
      >
        布局宽度
        <span className="font-mono text-[var(--lumi-text-primary)]">
          {selected.vars.readerContentWidth ?? width.default}px
        </span>
      </label>
      <input
        id="preset-width-range"
        type="range"
        min={width.min}
        max={width.max}
        step={width.step}
        value={selected.vars.readerContentWidth ?? width.default}
        onChange={(e) => onEdit({ readerContentWidth: Number(e.target.value) })}
        className="mt-1 w-full accent-[var(--lumi-accent)]"
      />
      <div className="mt-3 flex items-center gap-2">
        <span className="text-xs text-[var(--lumi-text-secondary)]">栏数</span>
        {[1, 2, 3].map((n) => (
          <button
            key={n}
            type="button"
            aria-pressed={columns === n}
            onClick={() => onEdit({ readerColumns: n })}
            className={cx(
              'rounded-[var(--lumi-radius-sm)] border px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              columns === n
                ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            {n}
          </button>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="text-xs text-[var(--lumi-text-secondary)]">设备适用</span>
        {(
          [
            { value: 'all', label: '全部设备' },
            { value: 'desktop', label: '仅桌面端' },
          ] as const
        ).map((opt) => (
          <button
            key={opt.value}
            type="button"
            aria-pressed={scope === opt.value}
            onClick={() => onEdit({ deviceScope: opt.value })}
            className={cx(
              'rounded-[var(--lumi-radius-sm)] border px-2.5 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
              scope === opt.value
                ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {scope === 'desktop' && (
        <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          桌面端生效：移动端应用此预设时忽略布局宽度与栏数。
        </p>
      )}
    </div>
  )
}
