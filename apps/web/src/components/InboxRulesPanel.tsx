/** InboxRulesPanel — F022 收件箱归类规则面板。
 *
 * 规则列表（顺序 = 应用顺序，第一条命中生效）：上移/下移、启停开关、
 * 编辑、删除；新建/编辑对话框（字段/操作符/值/目标工作区）；样本试跑
 * 框：dry-run 展示命中解释（纯读、不落库）。
 */

import { useState } from 'react'
import { ArrowDown, ArrowUp, FlaskConical, Plus, Trash2 } from 'lucide-react'
import {
  dryRunInboxRule,
  type InboxRuleDryRunResultView,
  type InboxRuleView,
} from '../api/client'
import { useInboxRuleMutations, useInboxRules, useWorkspaces } from '../api/queries'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Switch } from './ui/Switch'

function RuleEditorDialog({
  rule,
  onClose,
}: {
  rule: InboxRuleView | null
  onClose: () => void
}) {
  const { create, patch } = useInboxRuleMutations()
  const workspaces = useWorkspaces()
  const [field, setField] = useState(rule?.field ?? 'title')
  const [operator, setOperator] = useState(rule?.operator ?? 'contains')
  const [value, setValue] = useState(rule?.value ?? '')
  const [workspaceId, setWorkspaceId] = useState(rule?.targetWorkspaceId ?? '')
  const [error, setError] = useState<string | null>(null)
  const pending = create.isPending || patch.isPending

  function submit() {
    if (!value.trim() || !workspaceId) {
      setError('请填写匹配值并选择目标工作区。')
      return
    }
    const body = { field, operator, value: value.trim(), targetWorkspaceId: workspaceId }
    if (rule === null) {
      create.mutate(body, { onSuccess: onClose, onError: () => setError('创建失败，请检查输入。') })
    } else {
      patch.mutate({ id: rule.id, body }, { onSuccess: onClose, onError: () => setError('保存失败，请检查输入。') })
    }
  }

  return (
    <Dialog open onClose={onClose} title={rule === null ? '新建归类规则' : '编辑归类规则'}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex gap-2">
          <select
            aria-label="匹配字段"
            value={field}
            onChange={(e) => setField(e.target.value as 'source' | 'title')}
            className="min-h-11 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm"
          >
            <option value="title">标题</option>
            <option value="source">来源</option>
          </select>
          <select
            aria-label="匹配方式"
            value={operator}
            onChange={(e) => setOperator(e.target.value as 'contains' | 'equals')}
            className="min-h-11 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm"
          >
            <option value="contains">包含</option>
            <option value="equals">等于</option>
          </select>
        </div>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="匹配值（≤200 字）"
          aria-label="匹配值"
          maxLength={200}
          className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm"
        />
        <select
          aria-label="目标工作区"
          value={workspaceId}
          onChange={(e) => setWorkspaceId(e.target.value)}
          className="min-h-11 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm"
        >
          <option value="">选择目标工作区…</option>
          {(workspaces.data?.items ?? []).map((ws) => (
            <option key={ws.id} value={ws.id}>
              {ws.name}
            </option>
          ))}
        </select>
        {error ? (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {error}
          </p>
        ) : null}
      </div>
      <footer className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          取消
        </Button>
        <Button onClick={submit} disabled={pending}>
          保存
        </Button>
      </footer>
    </Dialog>
  )
}

function DryRunBox() {
  const [field, setField] = useState<'title' | 'source'>('title')
  const [value, setValue] = useState('')
  const [result, setResult] = useState<InboxRuleDryRunResultView | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    if (!value.trim()) return
    setRunning(true)
    setError(null)
    try {
      setResult(await dryRunInboxRule({ field, value: value.trim() }))
    } catch {
      setError('试跑失败，请稍后重试。')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2">
      <p className="flex items-center gap-1 text-xs font-medium text-[var(--lumi-text-secondary)]">
        <FlaskConical aria-hidden className="size-3.5" />
        样本试跑（不落库）
      </p>
      <div className="mt-2 flex gap-2">
        <select
          aria-label="试跑字段"
          value={field}
          onChange={(e) => setField(e.target.value as 'title' | 'source')}
          className="min-h-9 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs"
        >
          <option value="title">标题</option>
          <option value="source">来源</option>
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void run()
          }}
          placeholder="样本值"
          aria-label="试跑样本值"
          className="min-h-9 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs"
        />
        <Button size="sm" variant="secondary" onClick={() => void run()} disabled={running}>
          试跑
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {result ? (
        <p
          className="mt-1 text-xs text-[var(--lumi-text-secondary)]"
          data-lumi-dryrun-explanation=""
        >
          {result.explanation}
        </p>
      ) : null}
    </div>
  )
}

export default function InboxRulesPanel() {
  const rules = useInboxRules()
  const { patch, move, remove } = useInboxRuleMutations()
  const [editorFor, setEditorFor] = useState<'new' | InboxRuleView | null>(null)

  if (rules.isPending) return null
  if (rules.isError) {
    return (
      <p role="alert" className="text-xs text-[var(--lumi-danger)]">
        归类规则加载失败。
      </p>
    )
  }
  const items = rules.data?.items ?? []
  return (
    <details className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2" data-lumi-inbox-rules="">
      <summary className="cursor-pointer select-none text-xs font-medium text-[var(--lumi-text-secondary)]">
        归类规则（{items.length}）
      </summary>
      <ul className="mt-2 flex flex-col gap-1.5">
        {items.map((rule, index) => (
          <li
            key={rule.id}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
            data-lumi-inbox-rule-row=""
          >
            <Switch
              checked={rule.enabled}
              onCheckedChange={(next) => patch.mutate({ id: rule.id, body: { enabled: next } })}
              label={`启用规则 ${rule.value}`}
            />
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
              {rule.field === 'title' ? '标题' : '来源'} {rule.operator === 'contains' ? '包含' : '等于'}
              「{rule.value}」→ {rule.targetWorkspaceId}
            </span>
            <Button
              variant="ghost"
              size="sm"
              aria-label={`上移规则 ${rule.value}`}
              disabled={index === 0}
              onClick={() => move.mutate({ id: rule.id, direction: 'up' })}
            >
              <ArrowUp aria-hidden className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              aria-label="下移"
              disabled={index === items.length - 1}
              onClick={() => move.mutate({ id: rule.id, direction: 'down' })}
            >
              <ArrowDown aria-hidden className="size-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditorFor(rule)}>
              编辑
            </Button>
            <Button variant="ghost" size="sm" aria-label={`删除规则 ${rule.value}`} onClick={() => remove.mutate(rule.id)}>
              <Trash2 aria-hidden className="size-3.5" />
            </Button>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => setEditorFor('new')}>
          <Plus aria-hidden className="size-3.5" />
          新建规则
        </Button>
      </div>
      <DryRunBox />
      {editorFor !== null && (
        <RuleEditorDialog rule={editorFor === 'new' ? null : editorFor} onClose={() => setEditorFor(null)} />
      )}
    </details>
  )
}
