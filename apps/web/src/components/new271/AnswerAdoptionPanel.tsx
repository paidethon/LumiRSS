/** NEW-279 问答结论采纳 — 结论连同引用移入个人笔记。

- 采纳 = 结论 + 引用 + AI 来源标记（「来源：AI」行 + 机器锚）写入
  新建或既有笔记；标记永不摘除，用户可再改写；
- 改写带冲突保护：笔记被人工编辑过 → 409 note_diverged（附现状，
  绝不静默覆盖人工修改）；
- 删除只删采纳台账，笔记内容不动。 */

import { useCallback, useEffect, useState } from 'react'
import {
  createAnswerAdoption,
  deleteAnswerAdoption,
  listAnswerAdoptions,
  reviseAnswerAdoption,
  ApiError,
  type AnswerAdoption,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function AnswerAdoptionPanel({ answerText }: { answerText: string }) {
  const [conclusion, setConclusion] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [adoptions, setAdoptions] = useState<AnswerAdoption[]>([])
  const [revision, setRevision] = useState('')
  const [divergedContent, setDivergedContent] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setAdoptions(await listAnswerAdoptions())
      setLoaded(true)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function adopt(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    setDivergedContent('')
    try {
      await createAnswerAdoption({
        conclusion,
        model: 'conversation',
        newTitle: newTitle.trim() !== '' ? newTitle : undefined,
      })
      setConclusion('')
      await refresh()
      setNotice('已采纳到笔记（带「来源：AI」标记）。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function revise(adoption: AnswerAdoption): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    setDivergedContent('')
    try {
      await reviseAnswerAdoption(adoption.id, revision)
      setRevision('')
      await refresh()
      setNotice('结论已改写，AI 来源标记保留。')
    } catch (err) {
      if (err instanceof ApiError && err.errorType === 'note_diverged') {
        setDivergedContent(String(err.payload.noteContentMd ?? ''))
        setError('笔记已被直接修改；改写未应用（现状已给出，请自行整理后重试）。')
      } else {
        setError(errorText(err))
      }
    } finally {
      setBusy(false)
    }
  }

  async function remove(adoption: AnswerAdoption): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await deleteAnswerAdoption(adoption.id)
      await refresh()
      setNotice('已删除采纳记录（笔记内容未动）。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-answer-adoptions="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-adoption-conclusion" className="text-sm text-[var(--lumi-text-secondary)]">
          要采纳的结论（可改写后再采纳）
        </label>
        <textarea
          id="new271-adoption-conclusion"
          className={inputClass}
          rows={3}
          value={conclusion}
          placeholder={answerText.slice(0, 120) || '粘贴回答中的一个结论'}
          onChange={(e) => setConclusion(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-adoption-title" className="text-sm text-[var(--lumi-text-secondary)]">
          新笔记标题（留空 = 默认「AI 问答结论」）
        </label>
        <input
          id="new271-adoption-title"
          className={inputClass}
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
        />
      </div>
      <button type="button" className={buttonClass} disabled={busy || conclusion.trim() === ''} onClick={() => void adopt()}>
        采纳到个人笔记
      </button>
      {loaded && adoptions.length === 0 && <StatusLine tone="info">还没有采纳记录。</StatusLine>}
      {adoptions.map((adoption) => (
        <div key={adoption.id} data-new271-adoption={adoption.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-primary)]">
            {adoption.conclusion.slice(0, 200)}
          </p>
          <div className="flex flex-col gap-1">
            <label htmlFor={`new271-adoption-revise-${adoption.id}`} className="text-sm text-[var(--lumi-text-secondary)]">
              改写这条结论
            </label>
            <input
              id={`new271-adoption-revise-${adoption.id}`}
              className={inputClass}
              value={revision}
              onChange={(e) => setRevision(e.target.value)}
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className={buttonClass}
              disabled={busy || revision.trim() === ''}
              onClick={() => void revise(adoption)}
            >
              改写
            </button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void remove(adoption)}>
              删除记录
            </button>
          </div>
        </div>
      ))}
      {divergedContent !== '' && (
        <div data-new271-adoption-diverged="" className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <StatusLine tone="info">笔记现状（AI 未覆盖）：</StatusLine>
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-[var(--lumi-text-secondary)]">{divergedContent}</pre>
        </div>
      )}
      {notice !== '' && <StatusLine tone="ok">{notice}</StatusLine>}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>采纳与改写都保留 AI 来源标记；笔记被你手动改过后，改写会被拒绝而不是覆盖。</NoteText>
    </div>
  )
}
