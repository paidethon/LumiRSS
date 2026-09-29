/** NEW-277 模型配置用途约束 — 为某模型限定可处理的任务类型。

- 约束只对显式映射到用途的配置档生效（default 兜底不可约束）；
- 触发不允许的用途时服务端 409 ai_purpose_not_allowed，绝不静默换
  模型；可用 GET /ai/purpose-options 查看其他已配置的可用模型。 */

import { useState } from 'react'
import {
  getPurposeConstraint,
  getPurposeOptions,
  putPurposeConstraint,
  type PurposeOptions,
} from '../../api/new271'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

const PURPOSE_LABELS: Record<string, string> = {
  summary: '摘要',
  chat: '问答',
  translate: '翻译',
  embed: '向量',
  moderate: '审核',
  quiz: '测验',
}

export function PurposeConstraintsPanel() {
  const [profileId, setProfileId] = useState('')
  const [purposes, setPurposes] = useState<string[]>([])
  const [availablePurposes, setAvailablePurposes] = useState<string[]>([])
  const [saved, setSaved] = useState(false)
  const [optionsPurpose, setOptionsPurpose] = useState('')
  const [options, setOptions] = useState<PurposeOptions | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function togglePurpose(purpose: string): void {
    setSaved(false)
    setPurposes((prev) =>
      prev.includes(purpose) ? prev.filter((p) => p !== purpose) : [...prev, purpose],
    )
  }

  async function load(): Promise<void> {
    setBusy(true)
    setError('')
    setSaved(false)
    try {
      setAvailablePurposes([])
      const existing = await getPurposeConstraint(profileId.trim())
      if (existing !== null) {
        setPurposes(existing.allowedPurposes)
        setAvailablePurposes(existing.purposes)
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function save(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await putPurposeConstraint(profileId.trim(), purposes)
      setAvailablePurposes(result.purposes)
      setSaved(true)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function checkOptions(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      setOptions(await getPurposeOptions(optionsPurpose))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const purposeList = availablePurposes.length > 0 ? availablePurposes : Object.keys(PURPOSE_LABELS)

  return (
    <div data-new271-purpose-constraints="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex grow flex-col gap-1">
          <label htmlFor="new271-constraint-profile" className="text-sm text-[var(--lumi-text-secondary)]">
            配置档 ID
          </label>
          <input
            id="new271-constraint-profile"
            className={inputClass}
            value={profileId}
            onChange={(e) => setProfileId(e.target.value)}
          />
        </div>
        <button type="button" className={buttonClass} disabled={busy || profileId.trim() === ''} onClick={() => void load()}>
          读取
        </button>
      </div>
      {purposeList.length > 0 && (
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm text-[var(--lumi-text-secondary)]">允许该模型处理的任务类型</legend>
          {purposeList.map((purpose) => (
            <div key={purpose} className="flex items-center gap-2">
              <input
                type="checkbox"
                id={`new271-constraint-${purpose}`}
                checked={purposes.includes(purpose)}
                onChange={() => togglePurpose(purpose)}
              />
              <label htmlFor={`new271-constraint-${purpose}`} className="text-sm text-[var(--lumi-text-primary)]">
                {PURPOSE_LABELS[purpose] ?? purpose}
              </label>
            </div>
          ))}
        </fieldset>
      )}
      {purposeList.length > 0 && (
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void save()}>
          保存约束
        </button>
      )}
      {saved && <StatusLine tone="ok">约束已保存（触发不允许用途时将要求改选模型）。</StatusLine>}
      <div className="flex items-end gap-2 border-t border-[var(--lumi-border)] pt-3">
        <div className="flex grow flex-col gap-1">
          <label htmlFor="new271-options-purpose" className="text-sm text-[var(--lumi-text-secondary)]">
            查询某用途当前可选的模型
          </label>
          <input
            id="new271-options-purpose"
            className={inputClass}
            value={optionsPurpose}
            onChange={(e) => setOptionsPurpose(e.target.value)}
            placeholder="summary"
          />
        </div>
        <button type="button" className={buttonClass} disabled={busy || optionsPurpose.trim() === ''} onClick={() => void checkOptions()}>
          查询
        </button>
      </div>
      {options !== null && (
        <div data-new271-purpose-options="" className="flex flex-col gap-1">
          <StatusLine tone={options.blocked ? 'error' : 'info'}>
            {options.blocked ? '当前映射模型被约束阻断；' : '当前映射可用；'}
            可选模型：
            {options.options.map((option) => `${option.profileLabel}${option.eligible ? '' : '（被约束）'}`).join('、') || '无'}
          </StatusLine>
          <NoteText>{options.honestyNote}</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
