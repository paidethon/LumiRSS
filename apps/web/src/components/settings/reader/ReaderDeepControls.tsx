/** ReaderDeepControls — 0012 设置区（Gate 4/5/8/9 + Gate 6 主题包）。
 *
 * 拆出 AppearanceControls 之外的新增设置（Spec §17：避免把所有新设置
 * 无限堆进一个文件）；组件与 SettingItem/custom node 体系一致。 */

import { useEffect, useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { useAppSettings } from '../../../store/app-settings'
import type {
  ReaderChineseConversion,
  ReaderCodeHighlight,
  ReaderTextIndent,
} from '../../../store/app-settings'
import {
  downloadThemePack,
  exportThemePack,
  parseThemePack,
  previewThemePack,
  themePackToPatch,
  ThemePackError,
  type LumiThemePack,
} from '../../../lib/theme-pack'
import { listLocalFonts } from '../../../lib/reader-fonts'
import { Dialog } from '../../ui/Dialog'
import { Button } from '../../ui/Button'
import { Select } from '../../ui/Select'

// ---- Gate 4：中文深度排版 ----

export function ChineseTypographySettings() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        中文排版
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        面向中文长文阅读习惯的排版选项；不影响代码块、列表与标题。
      </p>

      <div className="mt-3 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
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

        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-[var(--lumi-text-primary)]">标点悬挂</p>
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              实验性 · 浏览器支持程度不同
            </p>
          </div>
          <Select
            aria-label="标点悬挂"
            value={settings.readerHangingPunctuation ? 'on' : 'off'}
            onChange={(e) => update({ readerHangingPunctuation: e.target.value === 'on' })}
            options={[
              { value: 'off', label: '关闭' },
              { value: 'on', label: '开启' },
            ]}
          />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-[var(--lumi-text-primary)]">简繁转换</p>
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              仅改变显示，不修改文章原始数据
            </p>
          </div>
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
              { value: 'tw', label: '繁体中文（台湾）' },
              { value: 'hk', label: '繁体中文（香港）' },
            ]}
          />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-[var(--lumi-text-primary)]">阅读时间估算</p>
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              在文章元信息行显示「约 N 分钟」（中英混排感知）
            </p>
          </div>
          <Select
            aria-label="阅读时间估算"
            value={settings.readerShowReadingTime ? 'on' : 'off'}
            onChange={(e) => update({ readerShowReadingTime: e.target.value === 'on' })}
            options={[
              { value: 'off', label: '隐藏' },
              { value: 'on', label: '显示' },
            ]}
          />
        </div>

        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-[var(--lumi-text-primary)]">词首强调</p>
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              实验性 · 对拉丁文词首进行视觉强调，不同用户体验可能不同
            </p>
          </div>
          <Select
            aria-label="词首强调"
            value={settings.readerBionic ? 'on' : 'off'}
            onChange={(e) => update({ readerBionic: e.target.value === 'on' })}
            options={[
              { value: 'off', label: '关闭' },
              { value: 'on', label: '开启' },
            ]}
          />
        </div>
      </div>
    </div>
  )
}

// ---- Gate 8：代码高亮 ----

export function CodeHighlightSettings() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        代码高亮
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        含代码块的文章按需加载语法高亮（Shiki，仅加载用到的语言）；不含代码
        的文章不承担任何加载成本。
      </p>
      <div className="mt-3 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-[var(--lumi-text-primary)]">语法高亮</span>
          <Select
            aria-label="语法高亮"
            value={settings.readerCodeHighlight}
            onChange={(e) => update({ readerCodeHighlight: e.target.value as ReaderCodeHighlight })}
            options={[
              { value: 'auto', label: '自动' },
              { value: 'off', label: '关闭' },
            ]}
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-[var(--lumi-text-primary)]">代码配色</span>
          <Select
            aria-label="代码配色"
            value={settings.readerCodeTheme}
            onChange={(e) => update({ readerCodeTheme: e.target.value })}
            disabled={settings.readerCodeHighlight === 'off'}
            options={[
              { value: 'auto', label: '跟随阅读器明暗' },
              { value: 'github-light', label: 'GitHub Light' },
              { value: 'github-dark', label: 'GitHub Dark' },
              { value: 'vitesse-light', label: 'Vitesse Light' },
              { value: 'vitesse-dark', label: 'Vitesse Dark' },
            ]}
          />
        </div>
      </div>
    </div>
  )
}

// ---- Gate 6：.lumitheme 主题包 ----

export function ReaderThemePackSettings() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fileRef = useRef<HTMLInputElement>(null)
  // 导入流程：parse → preview → 用户确认 → apply（Spec 冻结）
  const [pending, setPending] = useState<LumiThemePack | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 本地字体 id 集合（预览时检测「缺少字体」）
  const [localFontIds, setLocalFontIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    void listLocalFonts().then((fonts) => setLocalFontIds(new Set(fonts.map((f) => f.id))))
  }, [])

  const handleFile = (file: File) => {
    setError(null)
    void file
      .text()
      .then((text) => {
        setPending(parseThemePack(text))
      })
      .catch((e) => {
        setError(
          e instanceof ThemePackError
            ? `导入失败：${e.message}`
            : '导入失败：文件不是有效的 LumiRSS 阅读主题',
        )
      })
  }

  const confirmApply = () => {
    if (pending === null) return
    update(themePackToPatch(pending))
    setPending(null)
  }

  const preview = pending !== null ? previewThemePack(pending, (id) => localFontIds.has(id)) : null

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        阅读主题包
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        把当前阅读样式导出为 .lumitheme 文件分享，或导入他人的主题包
        （导入前先预览确认；兼容 0010a 旧版预设文件）。
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            const name = window.prompt('主题包名称：', '我的阅读主题')
            if (name === null) return
            downloadThemePack(exportThemePack(settings, { name }))
          }}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <Download aria-hidden className="size-3.5" /> 导出当前主题
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
        >
          <Upload aria-hidden className="size-3.5" /> 导入主题包
        </button>
        {error && (
          <span className="text-xs text-[var(--lumi-danger)]" role="alert">
            {error}
          </span>
        )}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".lumitheme,.json,application/json"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) handleFile(f)
          e.target.value = ''
        }}
      />

      {/* 预览确认对话框 */}
      <Dialog
        open={pending !== null}
        onClose={() => setPending(null)}
        title="导入阅读主题包"
        footer={
          <>
            <Button variant="secondary" onClick={() => setPending(null)}>
              取消
            </Button>
            <Button onClick={confirmApply}>应用主题</Button>
          </>
        }
      >
        {preview !== null && (
          <dl className="divide-y divide-[var(--lumi-separator)] text-sm">
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">名称</dt>
              <dd className="text-right text-[var(--lumi-text-primary)]">{preview.name}</dd>
            </div>
            {preview.description !== '' && (
              <div className="flex justify-between gap-4 py-2.5">
                <dt className="text-[var(--lumi-text-secondary)]">描述</dt>
                <dd className="max-w-64 text-right text-[var(--lumi-text-primary)]">
                  {preview.description}
                </dd>
              </div>
            )}
            {preview.author !== '' && (
              <div className="flex justify-between gap-4 py-2.5">
                <dt className="text-[var(--lumi-text-secondary)]">作者</dt>
                <dd className="text-[var(--lumi-text-primary)]">{preview.author}</dd>
              </div>
            )}
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">字体</dt>
              <dd className="text-[var(--lumi-text-primary)]">{preview.fontFamilyLabel}</dd>
            </div>
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">背景</dt>
              <dd className="text-[var(--lumi-text-primary)]">{preview.backgroundLabel}</dd>
            </div>
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">字号 / 行高</dt>
              <dd className="text-[var(--lumi-text-primary)]">
                {preview.fontSize}px / {preview.lineHeight}
              </dd>
            </div>
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">中文排版</dt>
              <dd className="text-[var(--lumi-text-primary)]">
                {preview.textIndent} · {preview.chineseConversion}
              </dd>
            </div>
            <div className="flex justify-between gap-4 py-2.5">
              <dt className="text-[var(--lumi-text-secondary)]">自定义 CSS</dt>
              <dd className="text-[var(--lumi-text-primary)]">
                {preview.hasCustomCss ? '包含（应用后替换当前自定义 CSS）' : '不包含'}
              </dd>
            </div>
            {preview.missingFont && (
              <div className="py-2.5">
                <p className="text-xs text-[var(--lumi-warning)]">
                  主题包引用的自定义字体在本机不存在，将回退到默认字体（不会自动联网寻找字体）。
                </p>
              </div>
            )}
          </dl>
        )}
      </Dialog>
    </div>
  )
}
