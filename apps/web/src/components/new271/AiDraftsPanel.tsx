/** NEW-272 AI 草稿版本对照 — 同一材料在不同提示方案下的候选草稿。

- 生成 = 一次有界 provider 调用（chat 通道）；保存 = 已有文本直接入库；
- 选两份 → diff 逐行对照（added/removed 行数）；组内单选 keep；
- keep/delete 绝不写 ai_summaries / lumi_notes（人工结论神圣）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  deleteAiDraft,
  generateAiDraft,
  getAiDraftDiff,
  keepAiDraft,
  listAiDrafts,
  type AiDraft,
  type AiDraftDiff,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function AiDraftsPanel({ entryRef }: { entryRef: string }) {
  const [drafts, setDrafts] = useState<AiDraft[]>([])
  const [schemeLabel, setSchemeLabel] = useState('')
  const [promptText, setPromptText] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [diff, setDiff] = useState<AiDraftDiff | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setDrafts(await listAiDrafts(entryRef))
      setLoaded(true)
    } catch (err) {
      setError(errorText(err))
    }
  }, [entryRef])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function generate(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await generateAiDraft(entryRef, { schemeLabel, promptText: promptText || undefined })
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function toggleSelect(id: string): void {
    setDiff(null)
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2),
    )
  }

  async function compare(): Promise<void> {
    if (selected.length !== 2) return
    setError('')
    try {
      setDiff(await getAiDraftDiff(selected[0], selected[1]))
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function keep(id: string): Promise<void> {
    setError('')
    try {
      await keepAiDraft(id)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function remove(id: string): Promise<void> {
    setError('')
    try {
      await deleteAiDraft(id)
      setSelected((prev) => prev.filter((x) => x !== id))
      await refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div data-new271-ai-drafts="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-draft-scheme" className="text-sm text-[var(--lumi-text-secondary)]">
          提示方案名称
        </label>
        <input
          id="new271-draft-scheme"
          className={inputClass}
          value={schemeLabel}
          onChange={(e) => setSchemeLabel(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-draft-prompt" className="text-sm text-[var(--lumi-text-secondary)]">
          提示词（可选，随草稿保存以便对照）
        </label>
        <textarea
          id="new271-draft-prompt"
          className={inputClass}
          rows={2}
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
        />
      </div>
      <button type="button" className={buttonClass} disabled={busy || schemeLabel.trim() === ''} onClick={() => void generate()}>
        {busy ? '生成中（一次有界调用）…' : '按此方案生成草稿'}
      </button>
      {loaded && drafts.length === 0 && <StatusLine tone="info">这篇还没有候选草稿。</StatusLine>}
      {drafts.length > 0 && (
        <ul className="flex flex-col gap-2" data-new271-draft-list="">
          {drafts.map((draft) => (
            <li key={draft.id} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`new271-draft-pick-${draft.id}`}
                  aria-label={`选中草稿 ${draft.schemeLabel} 参与对照`}
                  checked={selected.includes(draft.id)}
                  onChange={() => toggleSelect(draft.id)}
                />
                <label htmlFor={`new271-draft-pick-${draft.id}`} className="text-sm font-medium text-[var(--lumi-text-primary)]">
                  {draft.schemeLabel}
                  {draft.kept ? '（已保留）' : ''}
                </label>
              </div>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                {draft.draftText.slice(0, 200)}
                {draft.draftText.length > 200 ? '…' : ''}
              </p>
              <div className="flex gap-2">
                <button type="button" className={buttonClass} onClick={() => void keep(draft.id)}>
                  保留此稿
                </button>
                <button type="button" className={buttonClass} onClick={() => void remove(draft.id)}>
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {selected.length === 2 && (
        <button type="button" className={buttonClass} onClick={() => void compare()}>
          对照选中的两份草稿
        </button>
      )}
      {diff !== null && (
        <div data-new271-draft-diff="" className="flex flex-col gap-1">
          <StatusLine tone="info">
            差异：新增 {diff.addedLines} 行 / 删除 {diff.removedLines} 行
            {diff.identical ? '（两稿文本相同）' : ''}
          </StatusLine>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] p-2 text-xs leading-relaxed">
            {diff.unified}
          </pre>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>保留/删除草稿不会改写摘要或笔记里的人工结论。</NoteText>
    </div>
  )
}
