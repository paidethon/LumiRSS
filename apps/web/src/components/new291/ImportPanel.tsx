/** NEW-291 EML 拖入阅读 — 选择 .eml 文件导入为资料条目；清单可选中
 * 供本组其他工具使用；导入结果按 imported/failed/skipped/conflicts
 * 如实分栏（同 Message-ID 同正文 → 已跳过；不同正文 → 冲突队列）。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  importEmails,
  listEmailMaterials,
  type EmailMaterialSummary,
  type ImportResult,
} from '../../api/new291'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function ImportPanel({
  onSelect,
}: {
  onSelect?: (materialId: string) => void
}) {
  const [materials, setMaterials] = useState<EmailMaterialSummary[]>([])
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setMaterials(await listEmailMaterials())
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function onImport(): Promise<void> {
    const files = Array.from(fileRef.current?.files ?? [])
    if (files.length === 0) {
      setError('请先选择至少一个 .eml 文件。')
      return
    }
    setBusy(true)
    setError('')
    try {
      const payloads = await Promise.all(
        files.map(async (file) => ({
          filename: file.name,
          content: await file.text(),
        })),
      )
      setResult(await importEmails(payloads))
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-import="" className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">选择邮件文件（.eml，可多选，单文件 ≤4 MiB）</span>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".eml,message/rfc822"
          className={inputClass}
        />
      </label>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void onImport()}>
        {busy ? '导入中…' : '导入为资料条目'}
      </button>
      {result !== null && (
        <div data-new291-import-result="" className="flex flex-col gap-1">
          <StatusLine tone="ok">导入成功 {result.imported.length} 封；失败 {result.failed.length}；跳过 {result.skipped.length}；冲突 {result.conflicts.length}</StatusLine>
          {result.failed.map((f) => (
            <StatusLine key={f.filename} tone="error">
              {f.filename}：{f.reason}
            </StatusLine>
          ))}
          {result.skipped.map((s) => (
            <StatusLine key={`s-${s.filename}`} tone="info">
              已跳过 {s.filename}：{s.reason}
            </StatusLine>
          ))}
          {result.conflicts.map((c) => (
            <StatusLine key={`c-${c.conflictId}`} tone="info">
              冲突 {c.filename}：{c.reason}（可在「重复复核」中处理）
            </StatusLine>
          ))}
          <NoteText>{result.honestyNote}</NoteText>
        </div>
      )}
      <StatusLine tone="info">已导入 {materials.length} 封</StatusLine>
      <ul className="flex flex-col gap-1">
        {materials.map((m) => (
          <li key={m.id} className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-left text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => onSelect?.(m.id)}
            >
              {m.subject || '（无主题）'} — {m.fromAddr || '未知发件人'}
              {m.sourceLabel !== '' && ` · ${m.sourceLabel}`}
            </button>
          </li>
        ))}
      </ul>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
