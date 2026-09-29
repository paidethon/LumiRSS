/** NEW-274 AI 结果引用核验 — 对回答中的引用逐条定位原文。

- 每条引用 {index, entryRef, claim}：定位是字面子串匹配——命中带
  摘录；找不到/文章不可得都如实标出；系统绝不声称自动核验一切；
- 「已核对」必须用户显式确认；存在未定位引用时需勾选
  confirmMissing 才能标记（服务端强制，防止一键漂白）。 */

import { useState } from 'react'
import {
  createCitationCheck,
  markCitationChecked,
  type CitationCheck,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function CitationCheckPanel() {
  const [answerText, setAnswerText] = useState('')
  const [citationsText, setCitationsText] = useState('')
  const [check, setCheck] = useState<CitationCheck | null>(null)
  const [confirmMissing, setConfirmMissing] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  /** 引用行格式：entryRef | 被引述的原文片段（每行一条）。 */
  function parseCitations(): { index: number; entryRef: string; claim: string }[] {
    return citationsText
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line !== '')
      .map((line, index) => {
        const separator = line.indexOf('|')
        const entryRef = separator === -1 ? line : line.slice(0, separator).trim()
        const claim = separator === -1 ? '' : line.slice(separator + 1).trim()
        return { index: index + 1, entryRef, claim }
      })
  }

  async function run(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setCheck(
        await createCitationCheck({
          answerText,
          citations: parseCitations(),
        }),
      )
      setConfirmMissing(false)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function markChecked(): Promise<void> {
    if (check === null) return
    setBusy(true)
    setError('')
    try {
      setCheck(await markCitationChecked(check.id, confirmMissing))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const statusText: Record<string, string> = {
    found: '已定位',
    not_found: '原文中找不到',
    entry_unavailable: '文章不可得',
    unchecked: '未核验',
  }

  return (
    <div data-new271-citation-checks="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-citation-answer" className="text-sm text-[var(--lumi-text-secondary)]">
          待核验的回答文本
        </label>
        <textarea
          id="new271-citation-answer"
          className={inputClass}
          rows={3}
          value={answerText}
          onChange={(e) => setAnswerText(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-citation-claims" className="text-sm text-[var(--lumi-text-secondary)]">
          引用清单（每行：entryRef | 被引述的原文片段）
        </label>
        <textarea
          id="new271-citation-claims"
          className={inputClass}
          rows={3}
          value={citationsText}
          onChange={(e) => setCitationsText(e.target.value)}
          placeholder={'e1.abc | 温度升高会加快反应速率'}
        />
      </div>
      <button
        type="button"
        className={buttonClass}
        disabled={busy || answerText.trim() === ''}
        onClick={() => void run()}
      >
        {busy ? '核验中…' : '逐条定位引用'}
      </button>
      {check !== null && (
        <div data-new271-citation-result="" className="flex flex-col gap-2">
          <ul className="flex flex-col gap-1">
            {check.citations.map((citation) => (
              <li key={citation.index} data-new271-citation-status={citation.status} className="text-sm leading-relaxed text-[var(--lumi-text-primary)]">
                [{citation.index}] {citation.entryRef} — {statusText[citation.status] ?? citation.status}
                {citation.excerpt !== undefined && citation.excerpt !== '' && (
                  <span className="text-[var(--lumi-text-tertiary)]">（摘录：{citation.excerpt.slice(0, 60)}）</span>
                )}
              </li>
            ))}
          </ul>
          {check.missingCount > 0 && (
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="new271-citation-confirm-missing"
                checked={confirmMissing}
                onChange={(e) => setConfirmMissing(e.target.checked)}
              />
              <label htmlFor="new271-citation-confirm-missing" className="text-sm text-[var(--lumi-text-secondary)]">
                我知道有 {check.missingCount} 条引用未定位，仍确认标为已核对
              </label>
            </div>
          )}
          <button
            type="button"
            className={buttonClass}
            disabled={busy || check.checked || (check.missingCount > 0 && !confirmMissing)}
            onClick={() => void markChecked()}
          >
            {check.checked ? `已核对${check.confirmedMissing ? '（带未定位确认）' : ''}` : '标为已核对'}
          </button>
          <NoteText>{check.honestyNote}</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
