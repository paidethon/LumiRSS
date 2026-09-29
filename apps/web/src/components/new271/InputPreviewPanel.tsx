/** NEW-271 AI 任务输入预览 — 执行摘要/问答前展示将发送的确切范围。

- 预览 = POST /ai-input-preview（服务端零费用，不调用 provider）；
- 分段表如实列出「标题/来源/缓存摘要/正文/用户笔记/历史/问题」的
  收录与字符数；摘要只发正文（不含标题/来源/笔记）由 honestyNote
  说明，绝不虚报；
- 可选笔记是用户显式输入（≤2000），随问答发送时进入 userNote 段。 */

import { useState } from 'react'
import { previewAiInput, type AiInputPreview } from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function InputPreviewPanel({ entryRef }: { entryRef: string }) {
  const [purpose, setPurpose] = useState<'summary' | 'conversation'>('conversation')
  const [question, setQuestion] = useState('')
  const [note, setNote] = useState('')
  const [preview, setPreview] = useState<AiInputPreview | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setPreview(
        await previewAiInput(entryRef, {
          purpose,
          question: question || undefined,
          note: note || undefined,
        }),
      )
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-input-preview="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-preview-purpose" className="text-sm text-[var(--lumi-text-secondary)]">
          任务类型
        </label>
        <select
          id="new271-preview-purpose"
          className={inputClass}
          value={purpose}
          onChange={(e) => setPurpose(e.target.value as 'summary' | 'conversation')}
        >
          <option value="conversation">问答</option>
          <option value="summary">摘要</option>
        </select>
      </div>
      {purpose === 'conversation' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="new271-preview-question" className="text-sm text-[var(--lumi-text-secondary)]">
            本次问题（可选，预览口径）
          </label>
          <input
            id="new271-preview-question"
            className={inputClass}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>
      )}
      {purpose === 'conversation' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="new271-preview-note" className="text-sm text-[var(--lumi-text-secondary)]">
            随问发送的用户笔记（可选，≤2000 字符）
          </label>
          <textarea
            id="new271-preview-note"
            className={inputClass}
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
      )}
      <button type="button" className={buttonClass} disabled={busy} onClick={() => void run()}>
        {busy ? '生成预览中…' : '预览将发送的输入'}
      </button>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      {preview !== null && (
        <div data-new271-preview-result="" className="flex flex-col gap-2">
          <table className="w-full text-sm">
            <caption className="sr-only">将发送的输入分段</caption>
            <thead>
              <tr className="text-left text-[var(--lumi-text-tertiary)]">
                <th scope="col" className="py-1">分段</th>
                <th scope="col" className="py-1">收录</th>
                <th scope="col" className="py-1">字符数</th>
              </tr>
            </thead>
            <tbody>
              {preview.sections.map((section) => (
                <tr key={section.key} data-new271-preview-section={section.key}>
                  <td className="py-1 text-[var(--lumi-text-primary)]">{section.label}</td>
                  <td className="py-1 text-[var(--lumi-text-secondary)]">{section.included ? '发送' : '不发'}</td>
                  <td className="py-1 text-[var(--lumi-text-secondary)]">
                    {section.included ? section.effectiveChars : 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <NoteText>
            有效输入共 {preview.totalEffectiveChars} 字符
            {preview.truncated ? '（正文按上限截断）' : ''}
          </NoteText>
          <NoteText>{preview.honestyNote}</NoteText>
        </div>
      )}
    </div>
  )
}
