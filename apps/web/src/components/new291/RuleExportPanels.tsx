/** NEW-297 导入规则预览 / NEW-300 脱敏导出 — 预览与导入同一条变换
 * 路径（确认后应用于本批）；默认脱敏导出，勾选才保留地址/完整头，
 * removedFields 与载荷严格一致。 */

import { useRef, useState } from 'react'
import {
  exportEmail,
  importEmails,
  previewImportRules,
  type EmailExport,
  type ImportRule,
  type PreviewSample,
} from '../../api/new291'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function RulePreviewPanel({ onImported }: { onImported?: () => void }) {
  const [pattern, setPattern] = useState('')
  const [tag, setTag] = useState('')
  const [samples, setSamples] = useState<PreviewSample[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  function rules(): ImportRule[] {
    const built: ImportRule[] = []
    if (pattern.trim() !== '') {
      built.push({ kind: 'subject_clean', config: { pattern: pattern.trim(), replacement: '' } })
    }
    if (tag.trim() !== '') built.push({ kind: 'tag', config: { value: tag.trim() } })
    return built
  }

  async function preview(): Promise<void> {
    const files = Array.from(fileRef.current?.files ?? [])
    if (files.length === 0) {
      setError('请先选择样本 .eml 文件。')
      return
    }
    setBusy(true)
    setError('')
    try {
      const payloads = await Promise.all(
        files.map(async (file) => ({ filename: file.name, content: await file.text() })),
      )
      setSamples((await previewImportRules(payloads, rules())).samples)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function apply(): Promise<void> {
    const files = Array.from(fileRef.current?.files ?? [])
    if (files.length === 0) return
    setBusy(true)
    setError('')
    try {
      const payloads = await Promise.all(
        files.map(async (file) => ({ filename: file.name, content: await file.text() })),
      )
      await importEmails(payloads, rules())
      setSamples(null)
      onImported?.()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-rules="" className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">样本文件（.eml，预览零写入）</span>
        <input ref={fileRef} type="file" multiple accept=".eml" className={inputClass} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">主题清理正则（前缀删除，如 ^\[外部\]\s*）</span>
        <input type="text" className={inputClass} value={pattern} onChange={(e) => setPattern(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">本批统一标签</span>
        <input type="text" className={inputClass} value={tag} onChange={(e) => setTag(e.target.value)} />
      </label>
      <div className="flex gap-2">
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void preview()}>
          预览（零写入）
        </button>
        {samples !== null && (
          <button type="button" className={buttonClass} disabled={busy} onClick={() => void apply()}>
            确认并应用于本批
          </button>
        )}
      </div>
      {samples !== null && (
        <div data-new291-rule-samples="" className="flex flex-col gap-1">
          {samples.map((s) => (
            <p key={s.filename} className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
              {s.status === 'failed'
                ? `${s.filename}：失败——${s.reason}`
                : `${s.filename}：${s.subjectRaw} → ${s.subject}；标签 ${(s.tags ?? []).join('、') || '无'}；来源 ${s.sourceLabel || '无'}（${s.sourceOrigin}）`}
            </p>
          ))}
          <NoteText>预览与确认后的导入使用同一条规则应用路径。</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function ExportPanel({ materialId }: { materialId: string }) {
  const [keepAddresses, setKeepAddresses] = useState(false)
  const [keepHeaders, setKeepHeaders] = useState(false)
  const [exported, setExported] = useState<EmailExport | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setExported(await exportEmail(materialId, keepAddresses, keepHeaders))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-export="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input type="checkbox" checked={keepAddresses} onChange={(e) => setKeepAddresses(e.target.checked)} />
          保留地址（发件人 / 收件人，默认删除）
        </label>
        <label className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input type="checkbox" checked={keepHeaders} onChange={(e) => setKeepHeaders(e.target.checked)} />
          保留完整邮件头（默认只留 Message-ID 与日期）
        </label>
      </div>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void run()}>
        生成导出（默认脱敏）
      </button>
      {exported !== null && (
        <div data-new291-export-result="" className="flex flex-col gap-1">
          <StatusLine tone="ok">
            导出 {exported.exportId}；遮罩 {exported.maskedRegions.length} 处；删除字段 {exported.removedFields.length} 项
          </StatusLine>
          <ul className="flex flex-col gap-0.5">
            {exported.removedFields.map((r) => (
              <li key={r.field} className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                {r.field}：{r.reason}
              </li>
            ))}
            {exported.removedFields.length === 0 && (
              <li className="text-sm text-[var(--lumi-text-tertiary)]">未删除任何字段（你勾选了全部保留）。</li>
            )}
          </ul>
          <NoteText>{exported.honestyNote}</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
