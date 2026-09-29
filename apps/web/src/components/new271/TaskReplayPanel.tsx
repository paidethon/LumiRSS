/** NEW-276 AI 失败重放诊断 — 失败任务的脱敏诊断与两种重试路径。

- 诊断只含结构字段（类型/模型/用量/错误分类 + 请求形状）——正文与
  问题内容从不入库，因此绝不出现在诊断里（结构性脱敏）；
- mode=same：相同配置重试（仅摘要有界可重放）；mode=modified：
  修改后新建（conversation 必须提供新问题）。 */

import { useState } from 'react'
import {
  getReplayDiagnostic,
  replayTask,
  type ReplayDiagnostic,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function TaskReplayPanel() {
  const [taskId, setTaskId] = useState('')
  const [diagnostic, setDiagnostic] = useState<ReplayDiagnostic | null>(null)
  const [mode, setMode] = useState<'same' | 'modified'>('same')
  const [question, setQuestion] = useState('')
  const [outcome, setOutcome] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function load(): Promise<void> {
    setBusy(true)
    setError('')
    setOutcome('')
    try {
      setDiagnostic(await getReplayDiagnostic(taskId.trim()))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function replay(): Promise<void> {
    if (diagnostic === null) return
    setBusy(true)
    setError('')
    try {
      const result = await replayTask(diagnostic.id, {
        mode,
        question: mode === 'modified' ? question : undefined,
      })
      setOutcome(`已按「${mode === 'same' ? '相同配置' : '修改后'}」重放，新任务 ${result.replayTaskId}`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new271-task-replays="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-replay-task-id" className="text-sm text-[var(--lumi-text-secondary)]">
          失败任务 ID
        </label>
        <input
          id="new271-replay-task-id"
          className={inputClass}
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
        />
      </div>
      <button type="button" className={buttonClass} disabled={busy || taskId.trim() === ''} onClick={() => void load()}>
        {busy ? '载入中…' : '查看脱敏诊断'}
      </button>
      {diagnostic !== null && (
        <div data-new271-replay-diagnostic="" className="flex flex-col gap-2">
          <StatusLine tone="info">
            {diagnostic.kind} · {diagnostic.model || '未记录模型'} · 输入 {diagnostic.inputChars ?? '—'} 字符 ·{' '}
            {diagnostic.durationMs}ms · 失败：{diagnostic.errorType ?? '未知'}
          </StatusLine>
          <NoteText>{diagnostic.redactionNote}</NoteText>
          <StatusLine tone="info">端点：{diagnostic.requestShape.endpoint}</StatusLine>
          <NoteText>{diagnostic.requestShape.note}</NoteText>
          <fieldset className="flex flex-col gap-1">
            <legend className="text-sm text-[var(--lumi-text-secondary)]">重试方式</legend>
            <div className="flex items-center gap-2">
              <input
                type="radio"
                id="new271-replay-mode-same"
                name="new271-replay-mode"
                checked={mode === 'same'}
                onChange={() => setMode('same')}
                disabled={!diagnostic.replayModes.includes('same')}
              />
              <label htmlFor="new271-replay-mode-same" className="text-sm text-[var(--lumi-text-primary)]">
                相同配置重试
              </label>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="radio"
                id="new271-replay-mode-modified"
                name="new271-replay-mode"
                checked={mode === 'modified'}
                onChange={() => setMode('modified')}
              />
              <label htmlFor="new271-replay-mode-modified" className="text-sm text-[var(--lumi-text-primary)]">
                修改后新建
              </label>
            </div>
          </fieldset>
          {mode === 'modified' && diagnostic.kind === 'conversation' && (
            <div className="flex flex-col gap-1">
              <label htmlFor="new271-replay-question" className="text-sm text-[var(--lumi-text-secondary)]">
                新问题（原问题未入库，无法重用）
              </label>
              <input
                id="new271-replay-question"
                className={inputClass}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
            </div>
          )}
          <button
            type="button"
            className={buttonClass}
            disabled={
              busy ||
              (mode === 'same' && !diagnostic.replayModes.includes('same')) ||
              (mode === 'modified' && diagnostic.kind === 'conversation' && question.trim() === '')
            }
            onClick={() => void replay()}
          >
            重试
          </button>
        </div>
      )}
      {outcome !== '' && <StatusLine tone="ok">{outcome}</StatusLine>}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
