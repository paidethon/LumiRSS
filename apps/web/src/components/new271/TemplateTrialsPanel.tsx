/** NEW-273 提示模板试运行 — 启用前在少量样本上的试跑台账。

- 试跑 = 对 1..3 个样本各一次有界 provider 调用；逐样本如实展示
  {输入字符数, 输出, 状态}（不估算 token，实际用量就是调用次数与
  输入字符数）；
- 「启用」是显式动作（promote → 正式问答模板）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  listTemplateTrials,
  promoteTemplateTrial,
  runTemplateTrial,
  type TemplateTrial,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function TemplateTrialsPanel() {
  const [templateText, setTemplateText] = useState('')
  const [sampleTitle, setSampleTitle] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [trials, setTrials] = useState<TemplateTrial[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [promoteName, setPromoteName] = useState('')

  const refresh = useCallback(async () => {
    try {
      setTrials(await listTemplateTrials())
      setLoaded(true)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function run(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await runTemplateTrial({
        templateText,
        samples: [{ title: sampleTitle, text: sampleText }],
      })
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function promote(trialId: string): Promise<void> {
    setError('')
    try {
      await promoteTemplateTrial(trialId, promoteName)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div data-new271-template-trials="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-trial-template" className="text-sm text-[var(--lumi-text-secondary)]">
          模板提示词
        </label>
        <textarea
          id="new271-trial-template"
          className={inputClass}
          rows={3}
          value={templateText}
          onChange={(e) => setTemplateText(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-trial-sample-title" className="text-sm text-[var(--lumi-text-secondary)]">
          样本标题
        </label>
        <input
          id="new271-trial-sample-title"
          className={inputClass}
          value={sampleTitle}
          onChange={(e) => setSampleTitle(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="new271-trial-sample-text" className="text-sm text-[var(--lumi-text-secondary)]">
          样本正文（合成或本人选定）
        </label>
        <textarea
          id="new271-trial-sample-text"
          className={inputClass}
          rows={3}
          value={sampleText}
          onChange={(e) => setSampleText(e.target.value)}
        />
      </div>
      <button
        type="button"
        className={buttonClass}
        disabled={busy || templateText.trim() === '' || sampleText.trim() === ''}
        onClick={() => void run()}
      >
        {busy ? '试跑中（逐样本调用）…' : '试跑模板'}
      </button>
      {loaded && trials.length === 0 && <StatusLine tone="info">还没有试跑记录。</StatusLine>}
      {trials.map((trial) => (
        <div key={trial.id} data-new271-trial={trial.id} className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <StatusLine tone="info">
            试跑 {trial.results.length} 个样本 · 实际调用 {trial.results.length} 次 · 输入共{' '}
            {trial.results.reduce((sum, r) => sum + r.inputChars, 0)} 字符
            {trial.promotedTemplateId !== null ? ' · 已启用为正式模板' : ''}
          </StatusLine>
          {trial.results.map((result, index) => (
            <div key={index} className="flex flex-col gap-1">
              <StatusLine tone={result.status === 'success' ? 'ok' : 'error'}>
                {result.title}：{result.status === 'success' ? '成功' : `失败（${result.errorType ?? 'unknown'}）`}
              </StatusLine>
              {result.status === 'success' && (
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
                  {result.output.slice(0, 300)}
                </p>
              )}
            </div>
          ))}
          {trial.promotedTemplateId === null && (
            <div className="flex items-end gap-2">
              <div className="flex flex-col gap-1">
                <label htmlFor={`new271-trial-promote-name-${trial.id}`} className="text-sm text-[var(--lumi-text-secondary)]">
                  启用为正式模板的名称
                </label>
                <input
                  id={`new271-trial-promote-name-${trial.id}`}
                  className={inputClass}
                  value={promoteName}
                  onChange={(e) => setPromoteName(e.target.value)}
                />
              </div>
              <button
                type="button"
                className={buttonClass}
                disabled={promoteName.trim() === ''}
                onClick={() => void promote(trial.id)}
              >
                启用
              </button>
            </div>
          )}
        </div>
      ))}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>试跑是真实 provider 调用（计入用量）；未配置模型时会得到明确错误而不是空结果。</NoteText>
    </div>
  )
}
