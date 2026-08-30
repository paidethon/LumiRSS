/** ReaderFontManager — Reader 自定义字体管理（0012 Gate 2/3）。
 *
 * 两条通道（lib/reader-fonts）：
 * - 本地 WOFF2 上传（IndexedDB 持久化，刷新自动恢复）；
 * - 字体 URL（大型中文字体自托管；浏览器直接向该地址请求，
 *   附隐私提示；不下载复制到本地）。
 *
 * 交互（Legado/Reeder 字体管理 inspired，独立实现）：
 * - 列表 = 档位字体（内置四档）+ 本地字体 + URL 字体；
 * - 单选激活；删除正在使用的字体自动解除引用（AC3 fallback）。 */

import { useEffect, useRef, useState } from 'react'
import { Link2, Loader2, Trash2, Upload } from 'lucide-react'
import { type ReaderCustomFont, useAppSettings } from '../../../store/app-settings'
import {
  deleteFont,
  FontError,
  importLocalFont,
  importUrlFont,
  listLocalFonts,
} from '../../../lib/reader-fonts'
import { READER_FONT_LABELS } from '../../../lib/reader-style'
import { cx } from '../../ui/cx'

export function ReaderFontManager() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const [localFonts, setLocalFonts] = useState<ReaderCustomFont[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  // URL 表单
  const [urlDraft, setUrlDraft] = useState('')
  const [urlName, setUrlName] = useState('')
  const [showUrlForm, setShowUrlForm] = useState(false)

  useEffect(() => {
    void listLocalFonts().then(setLocalFonts)
  }, [])

  const refreshList = () => void listLocalFonts().then(setLocalFonts)

  const runAction = async (fn: () => Promise<string>) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      setNotice(await fn())
    } catch (e) {
      setError(e instanceof FontError ? e.message : '操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  const handleFile = (file: File) => {
    void runAction(async () => {
      const { font, duplicate } = await importLocalFont(file)
      refreshList()
      if (duplicate) return `「${font.name}」已存在（内容相同），未重复导入`
      update({ readerCustomFontId: font.id, readerFontUrl: null })
      return `已导入并启用「${font.name}」`
    })
  }

  const handleUrl = () => {
    void runAction(async () => {
      const font = await importUrlFont(urlDraft.trim(), urlName.trim() || urlDraft.trim())
      update({ readerFontUrl: font.url, readerFontUrlName: font.name, readerCustomFontId: null })
      setUrlDraft('')
      setUrlName('')
      setShowUrlForm(false)
      return `已加载并启用远程字体「${font.name}」`
    })
  }

  const handleDelete = (font: ReaderCustomFont) => {
    void runAction(async () => {
      await deleteFont(font.id)
      refreshList()
      // 删除正在使用的本地字体 → 解除引用，Reader 回退档位栈（AC3）
      if (settings.readerCustomFontId === font.id) {
        update({ readerCustomFontId: null })
      }
      return `已删除「${font.name}」`
    })
  }

  const clearUrlFont = () => {
    update({ readerFontUrl: null, readerFontUrlName: '' })
    setNotice('已停用远程字体，恢复档位字体')
  }

  const activeUrlFontLoaded =
    settings.readerFontUrl !== null && settings.readerCustomFontId === null

  return (
    <div className="py-3">
      <label className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
        自定义字体
      </label>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        上传 WOFF2 字体（保存在本地浏览器，离线可用）；大型中文字体建议用
        URL 方式自托管引用。
      </p>

      {/* 字体选择列表 */}
      <div className="mt-3 flex flex-col gap-1.5" role="radiogroup" aria-label="正文字体">
        {/* 档位字体（无自定义时选中） */}
        {(Object.keys(READER_FONT_LABELS) as (keyof typeof READER_FONT_LABELS)[]).map((key) => {
          const active = settings.readerCustomFontId === null && settings.readerFontUrl === null && settings.readerFontFamily === key
          return (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => update({ readerFontFamily: key, readerCustomFontId: null, readerFontUrl: null })}
              className={cx(
                'flex items-center gap-2 rounded-[var(--lumi-radius-md)] border px-3 py-2 text-left transition-colors duration-[var(--lumi-motion-fast)]',
                active
                  ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)]'
                  : 'border-[var(--lumi-border)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              <span
                aria-hidden
                className={cx(
                  'flex size-4 shrink-0 items-center justify-center rounded-full border',
                  active ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent)]' : 'border-[var(--lumi-border)]',
                )}
              />
              <span className="text-sm text-[var(--lumi-text-primary)]">
                {READER_FONT_LABELS[key]}
              </span>
            </button>
          )
        })}

        {/* 本地字体 */}
        {localFonts.map((font) => {
          const active = settings.readerCustomFontId === font.id
          return (
            <div
              key={font.id}
              className={cx(
                'flex items-center gap-2 rounded-[var(--lumi-radius-md)] border px-3 py-2 transition-colors duration-[var(--lumi-motion-fast)]',
                active
                  ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)]'
                  : 'border-[var(--lumi-border)]',
              )}
            >
              <button
                type="button"
                role="radio"
                aria-checked={active}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                onClick={() => update({ readerCustomFontId: font.id, readerFontUrl: null })}
              >
                <span
                  aria-hidden
                  className={cx(
                    'flex size-4 shrink-0 items-center justify-center rounded-full border',
                    active ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent)]' : 'border-[var(--lumi-border)]',
                  )}
                />
                <span className="truncate text-sm text-[var(--lumi-text-primary)]">{font.name}</span>
                <span className="shrink-0 text-[11px] text-[var(--lumi-text-tertiary)]">
                  {(font.size / 1024).toFixed(0)} KB
                </span>
              </button>
              <button
                type="button"
                aria-label={`删除字体 ${font.name}`}
                onClick={() => handleDelete(font)}
                className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
              >
                <Trash2 aria-hidden className="size-3.5" />
              </button>
            </div>
          )
        })}

        {/* URL 字体（当前已加载的远程字体） */}
        {activeUrlFontLoaded && settings.readerFontUrl !== null && (
          <div className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)] px-3 py-2">
            <button
              type="button"
              role="radio"
              aria-checked
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
              onClick={clearUrlFont}
            >
              <span
                aria-hidden
                className="flex size-4 shrink-0 items-center justify-center rounded-full border border-[var(--lumi-accent)] bg-[var(--lumi-accent)]"
              />
              <span className="truncate text-sm text-[var(--lumi-text-primary)]">
                {settings.readerFontUrlName || '远程字体'}
              </span>
              <span className="shrink-0 text-[11px] text-[var(--lumi-text-tertiary)]">URL</span>
            </button>
            <button
              type="button"
              aria-label="停用远程字体"
              onClick={clearUrlFont}
              className="flex size-7 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
            >
              <Trash2 aria-hidden className="size-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* 操作区 */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-50"
        >
          {busy ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Upload aria-hidden className="size-3.5" />}
          上传 WOFF2
        </button>
        <button
          type="button"
          onClick={() => setShowUrlForm((v) => !v)}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] disabled:opacity-50"
        >
          <Link2 aria-hidden className="size-3.5" /> 字体 URL
        </button>
        {error && <span className="text-xs text-[var(--lumi-danger)]" role="alert">{error}</span>}
        {notice && <span className="text-xs text-[var(--lumi-text-tertiary)]">{notice}</span>}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".woff2,font/woff2"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) handleFile(f)
          e.target.value = ''
        }}
      />

      {showUrlForm && (
        <div className="mt-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            输入自托管的 WOFF2 字体地址（仅 http/https）。隐私提示：启用后浏览器会
            向该地址所在的服务器发起字体请求；字体不会被下载保存到本地。
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <input
              type="url"
              value={urlDraft}
              onChange={(e) => setUrlDraft(e.target.value)}
              placeholder="https://your-domain.example/fonts/MyCJK.woff2"
              aria-label="字体 URL"
              className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
            />
            <input
              type="text"
              value={urlName}
              onChange={(e) => setUrlName(e.target.value)}
              placeholder="显示名（可选）"
              aria-label="字体显示名"
              className="w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-primary)]"
            />
            <button
              type="button"
              onClick={handleUrl}
              disabled={busy || urlDraft.trim() === ''}
              className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 py-1.5 text-xs font-medium text-[var(--lumi-accent-contrast)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-accent-hover)] disabled:opacity-50"
            >
              加载
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
