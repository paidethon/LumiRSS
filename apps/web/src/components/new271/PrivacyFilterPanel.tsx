/** NEW-278 AI 输入隐私过滤预览 — 显式字段/标注层排除 + 执行前差异。

- 过滤是【用户显式勾选的字段】（来源/缓存摘要/用户笔记），不是也
  绝不声称自动识别所有秘密；正文不在可排除词表内（没有正文的问答
  没有意义）；
- 执行前用 diff 端点查看「不过滤 vs 当前勾选」的差异（被剔除字符
  数如实给出）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  getPrivacyFilters,
  postPrivacyDiff,
  putPrivacyFilters,
  type PrivacyDiff,
  type PrivacyFilterView,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText } from './panel'

export function PrivacyFilterPanel({ entryRef }: { entryRef: string }) {
  const [view, setView] = useState<PrivacyFilterView | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [diff, setDiff] = useState<PrivacyDiff | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const current = await getPrivacyFilters()
      setView(current)
      setSelected(current.exclude)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  function toggle(key: string): void {
    setSaved(false)
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }

  async function save(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await putPrivacyFilters(selected)
      setView(result)
      setSaved(true)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function previewDiff(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setDiff(
        await postPrivacyDiff({ entryRef, purpose: 'conversation', note: '' }),
      )
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-privacy-filters="" className="flex flex-col gap-3">
      {view === null && <StatusLine tone="info">载入中…</StatusLine>}
      {view !== null && (
        <>
          <fieldset className="flex flex-col gap-1">
            <legend className="text-sm text-[var(--lumi-text-secondary)]">发送给模型前排除的字段</legend>
            {view.fields.map((field) => (
              <div key={field} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`new271-privacy-${field}`}
                  checked={selected.includes(field)}
                  onChange={() => toggle(field)}
                />
                <label htmlFor={`new271-privacy-${field}`} className="text-sm text-[var(--lumi-text-primary)]">
                  {view.fieldLabels[field] ?? field}
                </label>
              </div>
            ))}
          </fieldset>
          <button type="button" className={buttonClass} disabled={busy} onClick={() => void save()}>
            保存过滤选择
          </button>
          {saved && <StatusLine tone="ok">已保存；下次问答/摘要发送时生效。</StatusLine>}
          <button type="button" className={buttonClass} disabled={busy} onClick={() => void previewDiff()}>
            预览这篇文章的过滤差异
          </button>
          {diff !== null && (
            <div data-new271-privacy-diff="" className="flex flex-col gap-1">
              <StatusLine tone="info">
                被过滤掉 {diff.removedChars} 字符（排除：{diff.exclude.length > 0 ? diff.exclude.join('、') : '无'}）
              </StatusLine>
              <ul className="flex flex-col gap-0.5">
                {diff.sections.map((section) => (
                  <li key={section.key} className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                    {section.label}：{section.included ? `发送 ${section.effectiveChars} 字符` : '不发送'}
                    {section.excludedByFilter === true ? '（被过滤勾选剔除）' : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <NoteText>{view.honestyNote}</NoteText>
        </>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
