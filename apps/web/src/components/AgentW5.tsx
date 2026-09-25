/** AgentW5 — W5 Agent 工作台组件。
 *
 * - ThreadSearchBox（F095）：会话消息搜索（下拉结果 + 命中高亮转义；
 *   >50 截断标注）；点击打开并滚动到对应消息。
 * - ThreadSettingsButton（F094/F098）：资料范围（工作区 / 留空全库）
 *   + 工具权限（all / readonly / allowed 子集 / 每轮上限）；下轮生效。
 * - ThreadExportButton（F096）：范围（轮数）→ 预览 → 下载 .md。
 * - ApprovalPreviewSection（F097）：写操作预演（零业务写入）。
 * - BranchButton（F099）：「从这里分支」——复制可见上下文，绝不重放
 *   工具、不复制审批/副作用。
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Download, GitBranch, Search, Settings2, Trash2 } from 'lucide-react'
import {
  branchAgentThread,
  exportAgentThreadMarkdown,
  previewAgentApproval,
  previewAgentRecipe,
  previewAgentScope,
  searchAgentThreads,
  applyAgentResearchPreset,
  updateAgentThreadSettings,
  type AgentScopeSummary,
  type AgentThreadSearchHit,
  type ApprovalPreview,
} from '../api/client'
import type { AgentMessage } from '../api/client'
import {
  useAgentPauseMutation,
  useAgentRecipes,
  useAgentResumeMutation,
  useAgentRetryMutation,
  useAgentReviseApprovalMutation,
  useAgentUndoMutation,
  useCreateAgentRecipeMutation,
  useDeleteAgentRecipeMutation,
  useRunAgentRecipeMutation,
  useWorkspaces,
} from '../api/queries'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

/** 命中片段高亮：先转义 HTML，再包 <mark>（绝不注入原始片段）。 */
export function highlightSnippet(snippet: string, q: string): string {
  const escaped = snippet
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
  if (q.trim() === '') return escaped
  const safe = q.trim().replaceAll(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return escaped.replaceAll(new RegExp(safe, 'gi'), (m) => `<mark>${m}</mark>`)
}

// ---- F095 会话搜索 -----------------------------------------------------------

export function ThreadSearchBox({
  onOpen,
}: {
  onOpen: (threadId: string, messageSeq: number) => void
}) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const search = useQuery({
    queryKey: ['agent-thread-search', q],
    queryFn: ({ signal }) => searchAgentThreads(q.trim(), signal),
    enabled: open && q.trim().length >= 2,
  })
  const hits: AgentThreadSearchHit[] = search.data?.items ?? []

  return (
    <div className="relative px-2.5 pb-1" data-thread-search="">
      <div className="flex items-center gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-2">
        <Search aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          placeholder="搜索会话消息…"
          aria-label="搜索会话消息"
          className="min-h-8 w-full bg-transparent text-xs text-[var(--lumi-text-primary)] outline-none"
        />
      </div>
      {open && q.trim().length >= 2 && (
        <div
          role="listbox"
          aria-label="搜索结果"
          className="absolute left-2.5 right-2.5 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-1 shadow-lg"
        >
          {search.isPending && <p className="px-2 py-1.5 text-xs text-[var(--lumi-text-tertiary)]">搜索中…</p>}
          {search.data !== undefined && hits.length === 0 && (
            <p className="px-2 py-1.5 text-xs text-[var(--lumi-text-tertiary)]">没有匹配的消息。</p>
          )}
          {search.data?.truncated === true && (
            <p className="px-2 py-1 text-[10px] text-[var(--lumi-text-tertiary)]">结果超过 50 条，仅显示前 50 条。</p>
          )}
          <ul>
            {hits.map((hit) => (
              <li key={`${hit.threadId}:${hit.messageIndex}`}>
                <button
                  type="button"
                  role="option"
                  aria-selected={false}
                  data-search-hit={hit.threadId}
                  onClick={() => {
                    onOpen(hit.threadId, hit.messageIndex)
                    setOpen(false)
                  }}
                  className="w-full rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-left text-xs hover:bg-[var(--lumi-surface-hover)]"
                >
                  <span className="block truncate font-medium text-[var(--lumi-text-primary)]">{hit.threadTitle}</span>
                  <span className="text-[var(--lumi-text-tertiary)]">{hit.role} · </span>
                  <span
                    className="text-[var(--lumi-text-secondary)] [&_mark]:bg-[var(--lumi-accent-soft)] [&_mark]:text-[var(--lumi-accent-text)]"
                    dangerouslySetInnerHTML={{ __html: highlightSnippet(hit.snippet, q) }}
                  />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ---- F094/F098 会话设置 -------------------------------------------------------

export function ThreadSettingsButton({ threadId }: { threadId: string }) {
  const [open, setOpen] = useState(false)
  const workspaces = useWorkspaces()
  const [scopeWorkspace, setScopeWorkspace] = useState('')
  const [toolMode, setToolMode] = useState<'all' | 'readonly'>('all')
  const [allowedTools, setAllowedTools] = useState('')
  const [maxOps, setMaxOps] = useState('')
  const [budgetCalls, setBudgetCalls] = useState('')
  const [budgetTurns, setBudgetTurns] = useState('')
  const [saved, setSaved] = useState<string | null>(null)

  /** 当前选择 → 会话设置载荷（保存与 N151 范围预览共用一份口径）。 */
  function buildPayload() {
    const budgetEmpty = budgetCalls.trim() === '' && budgetTurns.trim() === ''
    return {
      scope: scopeWorkspace === '' ? null : { workspaceId: scopeWorkspace },
      clearScope: scopeWorkspace === '',
      toolPolicy:
        toolMode === 'all' && allowedTools.trim() === '' && maxOps.trim() === ''
          ? null
          : {
              mode: toolMode as 'all' | 'readonly',
              ...(allowedTools.trim() !== ''
                ? { allowedTools: allowedTools.split(/[,，]/).map((s) => s.trim()).filter(Boolean) }
                : {}),
              ...(maxOps.trim() !== '' ? { maxOpsPerTurn: Math.max(1, Math.min(50, Number(maxOps) || 50)) } : {}),
            },
      clearToolPolicy: toolMode === 'all' && allowedTools.trim() === '' && maxOps.trim() === '',
      // N165：线程级任务预算（两项皆空 = 清除预算约束）。
      budget:
        budgetEmpty
          ? null
          : {
              ...(budgetCalls.trim() !== '' ? { maxToolCalls: Math.max(1, Math.min(200, Number(budgetCalls) || 200)) } : {}),
              ...(budgetTurns.trim() !== '' ? { maxTurns: Math.max(1, Math.min(100, Number(budgetTurns) || 100)) } : {}),
            },
      clearBudget: budgetEmpty,
    }
  }

  const save = useMutation({
    mutationFn: () => updateAgentThreadSettings(threadId, buildPayload()),
    onSuccess: () => setSaved('已保存（下一轮对话生效）。'),
  })

  // N163：一键研究模式预设（readonly + 当前范围 + read 白名单 + 回合上限）。
  const research = useMutation({
    mutationFn: () => applyAgentResearchPreset(threadId),
  })

  // N151 授权范围摘要卡：选择变化 → 服务端解析 kind × refCount × toolCount
  // （refCount 服务端查询时解析，前端绝不伪造计数）。
  const scopePreview = useMutation({
    mutationFn: () => {
      const payload = buildPayload()
      return previewAgentScope({ scope: payload.scope, toolPolicy: payload.toolPolicy })
    },
  })
  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => scopePreview.mutate(), 250)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scopeWorkspace, toolMode, allowedTools, maxOps, budgetCalls, budgetTurns])
  const summary: AgentScopeSummary | null = scopePreview.data ?? null

  const scopeKindLabel =
    summary === null
      ? null
      : summary.kind === 'all'
        ? '全库（不锁定）'
        : summary.kind === 'workspace'
          ? '工作区'
          : '条目列表'

  return (
    <>
      <IconButton
        icon={<Settings2 aria-hidden className="size-4" />}
        label="会话设置"
        size="sm"
        touch
        onClick={() => setOpen(true)}
      />
      {open && (
        <Dialog
          open
          onClose={() => setOpen(false)}
          title="会话设置"
          footer={
            <div className="flex w-full justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>关闭</Button>
              <Button
                variant="secondary"
                size="sm"
                data-testid="research-preset-btn"
                disabled={research.isPending}
                onClick={() =>
                  research.mutate(undefined, {
                    onSuccess: () => {
                      setSaved('已应用研究模式（只读 + 当前范围 + 回合上限），下一轮生效。')
                      setOpen(false)
                    },
                  })
                }
              >
                {research.isPending ? '应用中…' : '研究模式'}
              </Button>
              <Button variant="primary" size="sm" disabled={save.isPending} onClick={() => save.mutate()}>
                {save.isPending ? '保存中…' : '保存'}
              </Button>
            </div>
          }
        >
          <div className="flex flex-col gap-3" data-thread-settings="">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">资料范围（留空 = 全库）</span>
              <select
                value={scopeWorkspace}
                onChange={(e) => setScopeWorkspace(e.target.value)}
                aria-label="资料范围工作区"
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
              >
                <option value="">全库（不锁定）</option>
                {(workspaces.data?.items ?? []).map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            </label>
            {/* N151 授权范围摘要卡：kind × refCount × toolCount。 */}
            <div
              data-scope-summary=""
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-2 text-xs"
            >
              <p className="font-medium text-[var(--lumi-text-primary)]">授权范围</p>
              {scopePreview.isPending && (
                <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">解析中…</p>
              )}
              {scopePreview.isError && (
                <p role="alert" className="mt-0.5 text-[var(--lumi-danger)]">
                  范围解析失败。
                </p>
              )}
              {summary !== null && !scopePreview.isPending && (
                <p className="mt-0.5 text-[var(--lumi-text-secondary)]">
                  {scopeKindLabel} ·{' '}
                  {summary.refCount === null ? '条目不限' : `${summary.refCount} 条`} ·{' '}
                  {summary.toolCount} 个工具可用
                </p>
              )}
            </div>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">工具权限</span>
              <select
                value={toolMode}
                onChange={(e) => setToolMode(e.target.value as 'all' | 'readonly')}
                aria-label="工具权限模式"
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
              >
                <option value="all">全部工具</option>
                <option value="readonly">只读（禁写）</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">仅允许的工具（逗号分隔，可选）</span>
              <input
                type="text"
                value={allowedTools}
                onChange={(e) => setAllowedTools(e.target.value)}
                placeholder="search, rag_search"
                aria-label="仅允许的工具"
                className={inputCls}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">每轮工具调用上限（1–50，可选）</span>
              <input
                type="number"
                min={1}
                max={50}
                value={maxOps}
                onChange={(e) => setMaxOps(e.target.value)}
                aria-label="每轮工具调用上限"
                className={inputCls}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">任务预算 · 工具调用总数上限（1–200，可选）</span>
              <input
                type="number"
                min={1}
                max={200}
                value={budgetCalls}
                onChange={(e) => setBudgetCalls(e.target.value)}
                aria-label="任务预算工具调用上限"
                className={inputCls}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">任务预算 · 回合数上限（1–100，可选）</span>
              <input
                type="number"
                min={1}
                max={100}
                value={budgetTurns}
                onChange={(e) => setBudgetTurns(e.target.value)}
                aria-label="任务预算回合上限"
                className={inputCls}
              />
            </label>
            <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
              设置在本轮结束后生效（下一轮读取）；进行中的回合不受影响。预算耗尽时回合会以 budget_exhausted 终止并展示消耗摘要（token 未上报时显示 unknown）。
            </p>
            {saved !== null && (
              <p role="status" className="text-xs text-[var(--lumi-text-primary)]">{saved}</p>
            )}
            {save.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                {save.error instanceof Error ? save.error.message : '保存失败，请稍后重试。'}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </>
  )
}

// ---- F096 会话导出 ------------------------------------------------------------

export function ThreadExportButton({ threadId }: { threadId: string }) {
  const [open, setOpen] = useState(false)
  const [rounds, setRounds] = useState('5')
  const [preview, setPreview] = useState<string | null>(null)

  const build = useMutation({
    mutationFn: () => exportAgentThreadMarkdown(threadId, Math.max(1, Math.min(20, Number(rounds) || 5))),
    onSuccess: setPreview,
  })

  function download() {
    if (preview === null) return
    const blob = new Blob([preview], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `agent-thread-${threadId.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <IconButton
        icon={<Download aria-hidden className="size-4" />}
        label="导出会话"
        size="sm"
        touch
        onClick={() => setOpen(true)}
      />
      {open && (
        <Dialog
          open
          onClose={() => setOpen(false)}
          title="导出会话（Markdown）"
          panelClassName="max-w-xl"
          footer={
            <div className="flex w-full justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>关闭</Button>
              {preview !== null && (
                <Button variant="primary" size="sm" onClick={download}>下载 .md</Button>
              )}
            </div>
          }
        >
          <div className="flex flex-col gap-2" data-thread-export="">
            <label className="flex items-center gap-2 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">导出最近轮数（1–20）</span>
              <input
                type="number"
                min={1}
                max={20}
                value={rounds}
                onChange={(e) => setRounds(e.target.value)}
                aria-label="导出轮数"
                className="w-20 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)]"
              />
              <Button variant="secondary" size="sm" disabled={build.isPending} onClick={() => build.mutate()}>
                {build.isPending ? '生成中…' : '生成预览'}
              </Button>
            </label>
            {preview !== null && (
              <pre
                data-export-preview=""
                className="max-h-64 overflow-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5 text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]"
              >
                {preview}
              </pre>
            )}
            {build.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                {build.error instanceof Error ? build.error.message : '导出失败，请稍后重试。'}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </>
  )
}

// ---- F097 写操作预演 ----------------------------------------------------------

export function ApprovalPreviewSection({ threadId, approvalId }: { threadId: string; approvalId: string }) {
  const [preview, setPreview] = useState<ApprovalPreview | null>(null)
  const run = useMutation({
    mutationFn: () => previewAgentApproval(threadId, approvalId),
    onSuccess: setPreview,
  })
  return (
    <div className="mt-2" data-approval-preview="">
      {!preview && (
        <Button size="sm" variant="ghost" disabled={run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? '预演中…' : '查看影响'}
        </Button>
      )}
      {preview !== null && (
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 text-xs">
          <p className="font-medium text-[var(--lumi-text-primary)]">预演（零写入）目标：{String(preview.target ?? '—')}</p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {preview.changes.map((change) => (
              <li key={change.field} className="text-[var(--lumi-text-secondary)]">
                {change.field}: {String(change.from ?? '—')} → {String(change.to ?? '—')}
              </li>
            ))}
          </ul>
          {preview.uncertain.length > 0 && (
            <p className="mt-1 text-[var(--lumi-text-tertiary)]">不确定项 {preview.uncertain.length} 处（执行时如实汇报）。</p>
          )}
        </div>
      )}
      {run.isError && (
        <p role="alert" className="mt-1 text-[11px] text-[var(--lumi-danger)]">
          {run.error instanceof Error ? run.error.message : '预演失败。'}
        </p>
      )}
    </div>
  )
}

// ---- N166 工具执行时间线 ---------------------------------------------------------

/** N166：单条工具步骤行（时间线）：名称 · 真实耗时 · 状态 · 脱敏参数摘要
 * （F097 _redact 口径，密钥形态值绝不出现）。
 * N168：retried/replayed 标注；N169：可撤销写步骤的差异撤销入口。 */
export function ToolTimelineRow({ message }: { message: AgentMessage }) {
  const content = message.content
  const name = typeof content['name'] === 'string' ? content['name'] : ''
  const result = 'result' in content ? content['result'] : content
  const durationMs = content['durationMs']
  const resultType = content['resultType']
  const maskedSummary = content['maskedArgsSummary']
  const stepId = typeof content['stepId'] === 'string' ? content['stepId'] : null
  const undoable = content['undoable'] === true
  const retried = content['retried'] === true
  const replayed = content['replayed'] === true
  const undoOf = typeof content['undoOf'] === 'string' ? content['undoOf'] : null
  return (
    <div
      data-timeline-row={content['callId'] ? String(content['callId']) : undefined}
      className={cx(
        'max-w-[95%] self-start rounded-[var(--lumi-radius-md)] border px-2.5 py-1.5',
        resultType === 'error' ? 'border-[var(--lumi-danger)]' : 'border-[var(--lumi-border)]',
        undoOf !== null && 'opacity-75',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <p className="text-[11px] font-medium text-[var(--lumi-text-tertiary)]">
          工具{name !== '' ? ` · ${name}` : ''}
        </p>
        {typeof durationMs === 'number' && (
          <span
            data-timeline-duration={String(durationMs)}
            className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]"
          >
            {durationMs} ms
          </span>
        )}
        {typeof resultType === 'string' && (
          <span
            data-timeline-result-type={resultType}
            className={cx(
              'rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px]',
              resultType === 'error'
                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-danger)]'
                : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
            )}
          >
            {resultType === 'error' ? '失败' : resultType === 'result' ? '成功' : resultType}
          </span>
        )}
        {retried && (
          <span className="rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
            重试
          </span>
        )}
        {replayed && (
          <span className="rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
            幂等重放
          </span>
        )}
      </div>
      {typeof maskedSummary === 'string' && maskedSummary !== '' && (
        <p
          data-timeline-args-summary=""
          title="参数摘要（敏感值已打码）"
          className="mt-0.5 truncate font-mono text-[10px] text-[var(--lumi-text-tertiary)]"
        >
          {maskedSummary}
        </p>
      )}
      <pre className="mt-1 overflow-x-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--lumi-text-secondary)]">
        {prettyJson(result)}
      </pre>
      {stepId !== null && undoable && <UndoStepButton threadId={message.threadId} stepId={stepId} />}
    </div>
  )
}

/** 等宽卡片里的 pretty JSON（截断保护 DOM）。 */
function prettyJson(value: unknown, maxChars = 800): string {
  let text: string
  try {
    text = JSON.stringify(value, null, 2) ?? 'null'
  } catch {
    text = String(value)
  }
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text
}

// ---- F099 对话分支 ------------------------------------------------------------

export function BranchButton({
  threadId,
  messageSeq,
  onBranched,
}: {
  threadId: string
  messageSeq: number
  onBranched: (newThreadId: string) => void
}) {
  const branch = useMutation({
    mutationFn: () => branchAgentThread(threadId, messageSeq),
    onSuccess: (result) => onBranched(result.thread.id),
  })
  return (
    <span className="inline-flex flex-col items-start">
      <Button
        size="sm"
        variant="ghost"
        disabled={branch.isPending}
        aria-label={`从消息 ${messageSeq} 分支`}
        onClick={() => branch.mutate()}
        className="opacity-0 transition-opacity group-hover/message:opacity-100 focus-visible:opacity-100 max-lg:opacity-100"
      >
        <GitBranch aria-hidden className="mr-1 inline size-3" />
        分支
      </Button>
      {branch.isError && (
        <span role="alert" className="text-[10px] text-[var(--lumi-danger)]">
          {branch.error instanceof Error ? branch.error.message : '分支失败。'}
        </span>
      )}
    </span>
  )
}

/** 分支来源徽标（会话 header 内）。 */
export function BranchBadge({ branchOf }: { branchOf: string | null | undefined }) {
  if (branchOf == null || branchOf === '') return null
  return (
    <span
      data-branch-badge=""
      className="shrink-0 rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]"
      title={`分支自 ${branchOf}`}
    >
      分支自…
    </span>
  )
}

// ---- N164 暂停 / 续接 ---------------------------------------------------------

/** N164：任务暂停与续接。暂停在服务端工具间检查点生效（诚实 409 无可
 * 暂停对象）；续接复用 transcript 中已执行步骤的结果，绝不重复副作用。
 * 暂停期间过期的批准由服务端要求重新确认（新批准行）。 */
export function PauseResumeControls({ threadId, processing }: { threadId: string; processing: boolean }) {
  const pause = useAgentPauseMutation(threadId)
  const resume = useAgentResumeMutation(threadId)
  return (
    <span className="inline-flex items-center gap-1" data-pause-resume="">
      <Button
        size="sm"
        variant="ghost"
        disabled={processing || pause.isPending}
        data-action="pause"
        onClick={() => pause.mutate()}
      >
        {pause.isPending ? '暂停中…' : '暂停'}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={processing || resume.isPending}
        data-action="resume"
        onClick={() => resume.mutate()}
      >
        {resume.isPending ? '续接中…' : '续接'}
      </Button>
      {(pause.isError || resume.isError) && (
        <span role="alert" className="max-w-40 truncate text-[10px] text-[var(--lumi-danger)]">
          {pause.isError
            ? pause.error.message
            : resume.isError
              ? resume.error.message
              : null}
        </span>
      )}
    </span>
  )
}

// ---- N168 失败步骤重试 ---------------------------------------------------------

/** N168：只重跑失败/未完成的步骤（已完成步骤复用 transcript 结果）。 */
export function ThreadRetryButton({ threadId, processing }: { threadId: string; processing: boolean }) {
  const retry = useAgentRetryMutation(threadId)
  return (
    <span className="inline-flex items-center gap-1" data-retry-control="">
      <Button
        size="sm"
        variant="ghost"
        disabled={processing || retry.isPending}
        data-action="retry-steps"
        onClick={() => retry.mutate()}
      >
        {retry.isPending ? '重试中…' : '重试失败步骤'}
      </Button>
      {retry.isError && (
        <span role="alert" className="max-w-40 truncate text-[10px] text-[var(--lumi-danger)]">
          {retry.error.message}
        </span>
      )}
    </span>
  )
}

// ---- N167 批准内容修改 ----------------------------------------------------------

/** N167：批准前编辑参数 → 修订产生新批准行（绑定新 args_hash），旧批准
 * 作废（take → 410）。编辑失败（非法 JSON）在本地拦截。 */
export function ApprovalEditSection({
  threadId,
  approvalId,
  args,
}: {
  threadId: string
  approvalId: string
  args: Record<string, unknown>
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const revise = useAgentReviseApprovalMutation(threadId)

  const start = () => {
    setText(JSON.stringify(args, null, 2))
    setLocalError(null)
    setOpen(true)
  }

  const submit = () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      setLocalError('参数不是合法 JSON。')
      return
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setLocalError('参数必须是 JSON 对象。')
      return
    }
    revise.mutate(
      { approvalId, newArgs: parsed as Record<string, unknown> },
      { onSuccess: () => setOpen(false) },
    )
  }

  return (
    <div data-approval-edit="">
      {!open ? (
        <Button size="sm" variant="ghost" data-action="edit-approval" onClick={start}>
          编辑参数
        </Button>
      ) : (
        <div className="mt-1 flex flex-col gap-1.5">
          <label className="flex flex-col gap-1 text-[11px]">
            <span className="text-[var(--lumi-text-secondary)]">修订后的参数（JSON；保存后旧批准作废）</span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={Math.min(10, text.split('\n').length + 1)}
              aria-label="修订批准参数"
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 font-mono text-[11px] text-[var(--lumi-text-primary)] focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]"
            />
          </label>
          {localError !== null && (
            <p role="alert" className="text-[11px] text-[var(--lumi-danger)]">{localError}</p>
          )}
          {revise.isError && (
            <p role="alert" className="text-[11px] text-[var(--lumi-danger)]">
              {revise.error instanceof Error ? revise.error.message : '修订失败。'}
            </p>
          )}
          <div className="flex gap-2">
            <Button size="sm" variant="primary" disabled={revise.isPending} data-action="save-revision" onClick={submit}>
              {revise.isPending ? '保存中…' : '保存并重新批准'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>取消</Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- N169 差异撤销 -------------------------------------------------------------

/** N169：对可撤销的写步骤回滚（对象写入后被改动过 → 服务端冲突报告并跳过）。 */
export function UndoStepButton({ threadId, stepId }: { threadId: string; stepId: string }) {
  const undo = useAgentUndoMutation(threadId)
  return (
    <span className="inline-flex items-center gap-1" data-undo-control={stepId}>
      <Button
        size="sm"
        variant="ghost"
        disabled={undo.isPending}
        data-action="undo-step"
        onClick={() => undo.mutate(stepId)}
      >
        {undo.isPending ? '撤销中…' : '撤销'}
      </Button>
      {undo.data !== undefined && undo.data.undone === false && undo.data.conflictReason !== null && (
        <span role="status" className="text-[10px] text-[var(--lumi-text-tertiary)]" title={undo.data.conflictReason}>
          冲突跳过
        </span>
      )}
      {undo.isError && (
        <span role="alert" className="text-[10px] text-[var(--lumi-danger)]">
          {undo.error instanceof Error ? undo.error.message : '撤销失败。'}
        </span>
      )}
    </span>
  )
}

// ---- N170 任务配方 -------------------------------------------------------------

/** N170：配方面板（保存 / 列表 / 运行前预览 / 运行）。运行创建新会话：
 * 白名单落成会话 toolPolicy（服务端强制），scope 落成会话范围。 */
export function RecipePanel({
  onRun,
}: {
  onRun: (threadId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const recipes = useAgentRecipes()
  const create = useCreateAgentRecipeMutation()
  const remove = useDeleteAgentRecipeMutation()
  const preview = useAgentRecipePreview(onRun)
  const [name, setName] = useState('')
  const [input, setInput] = useState('')
  const [whitelist, setWhitelist] = useState('')
  const [scopeId, setScopeId] = useState('')
  const workspaces = useWorkspaces()

  const items = recipes.data?.items ?? []

  function submitCreate() {
    create.mutate(
      {
        name: name.trim(),
        input: input.trim(),
        toolWhitelist: whitelist.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
        scope: scopeId === '' ? null : { workspaceId: scopeId },
      },
      { onSuccess: () => { setName(''); setInput(''); setWhitelist(''); setScopeId('') } },
    )
  }

  return (
    <div className="px-2.5 pb-2" data-recipe-panel="">
      <div className="flex items-center gap-1.5 py-1">
        <p className="text-xs font-semibold text-[var(--lumi-text-primary)]">配方</p>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          data-action="new-recipe"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '收起' : '新建'}
        </Button>
      </div>
      {open && (
        <div className="mb-2 flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="配方名称"
            aria-label="配方名称"
            className={inputCls}
          />
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="首条消息内容"
            aria-label="配方首条消息"
            rows={2}
            className={inputCls}
          />
          <input
            type="text"
            value={whitelist}
            onChange={(e) => setWhitelist(e.target.value)}
            placeholder="工具白名单（逗号分隔，如 search, add_to_workspace）"
            aria-label="配方工具白名单"
            className={inputCls}
          />
          <select
            value={scopeId}
            onChange={(e) => setScopeId(e.target.value)}
            aria-label="配方资料范围"
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm text-[var(--lumi-text-primary)]"
          >
            <option value="">全库（不锁定）</option>
            {(workspaces.data?.items ?? []).map((w) => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </select>
          {create.isError && (
            <p role="alert" className="text-[11px] text-[var(--lumi-danger)]">
              {create.error instanceof Error ? create.error.message : '保存失败。'}
            </p>
          )}
          <Button
            size="sm"
            variant="secondary"
            data-action="save-recipe"
            disabled={create.isPending || name.trim() === '' || input.trim() === '' || whitelist.trim() === ''}
            onClick={submitCreate}
          >
            {create.isPending ? '保存中…' : '保存配方'}
          </Button>
        </div>
      )}
      {recipes.isPending && <p className="py-1 text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
      {recipes.isError && (
        <p role="alert" className="py-1 text-xs text-[var(--lumi-danger)]">配方加载失败。</p>
      )}
      {recipes.data !== undefined && items.length === 0 && (
        <p className="py-1 text-xs text-[var(--lumi-text-tertiary)]">还没有配方</p>
      )}
      <ul className="flex flex-col gap-0.5">
        {items.map((recipe) => (
          <li key={recipe.id} data-recipe-item={recipe.id} className="group flex items-center gap-1">
            <button
              type="button"
              data-action="preview-recipe"
              onClick={() => preview.open(recipe.id)}
              className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-left text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              <span className="block truncate font-medium" title={recipe.name}>{recipe.name}</span>
              <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
                {recipe.toolWhitelist.length} 个工具
              </span>
            </button>
            <IconButton
              icon={<Trash2 aria-hidden className="size-3.5" />}
              label={`删除配方 ${recipe.name}`}
              size="sm"
              touch
              disabled={remove.isPending}
              onClick={() => remove.mutate(recipe.id)}
              className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 max-lg:opacity-100"
            />
          </li>
        ))}
      </ul>
      {preview.dialog}
    </div>
  )
}

/** N170 预览对话框（内部状态钩子：返回 dialog 节点 + open）。运行
 * 成功 → 关闭对话框并回调 onRun（打开服务端创建的新会话）。 */
function useAgentRecipePreview(onRun: (threadId: string) => void) {
  const [recipeId, setRecipeId] = useState<string | null>(null)
  const preview = useQuery({
    queryKey: ['agent', 'recipe-preview', recipeId],
    queryFn: ({ signal }) => previewAgentRecipe(recipeId!, signal),
    enabled: recipeId !== null,
  })
  const run = useRunAgentRecipeMutation()
  const dialog =
    recipeId !== null ? (
      <Dialog
        open
        onClose={() => setRecipeId(null)}
        title="运行配方（预览）"
        panelClassName="max-w-md"
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRecipeId(null)}>取消</Button>
            <Button
              variant="primary"
              size="sm"
              data-action="confirm-run-recipe"
              disabled={run.isPending || preview.isPending}
              onClick={() =>
                run.mutate(recipeId, {
                  onSuccess: (result) => {
                    setRecipeId(null)
                    onRun(result.thread.id)
                  },
                })
              }
            >
              {run.isPending ? '运行中…' : '运行（创建新会话）'}
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-2 text-xs" data-recipe-preview="">
          {preview.isPending && <p className="text-[var(--lumi-text-tertiary)]">生成预览中…</p>}
          {preview.isError && (
            <p role="alert" className="text-[var(--lumi-danger)]">
              {preview.error instanceof Error ? preview.error.message : '预览失败。'}
            </p>
          )}
          {preview.data !== undefined && (
            <>
              <p className="font-medium text-[var(--lumi-text-primary)]">{preview.data.name}</p>
              <p className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] px-2 py-1.5 text-[var(--lumi-text-secondary)]">
                {preview.data.input}
              </p>
              <p className="text-[var(--lumi-text-secondary)]">
                工具白名单：{preview.data.toolWhitelist.join('、')}
              </p>
              <p className="text-[var(--lumi-text-tertiary)]">
                范围：{preview.data.scope === null ? '全库' : JSON.stringify(preview.data.scope)}
              </p>
              <p className="text-[var(--lumi-text-tertiary)]">{preview.data.note}</p>
            </>
          )}
        </div>
      </Dialog>
    ) : null
  return { open: (id: string) => setRecipeId(id), dialog }
}
