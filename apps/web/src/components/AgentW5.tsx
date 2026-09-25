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
import { Download, GitBranch, Search, Settings2 } from 'lucide-react'
import {
  branchAgentThread,
  exportAgentThreadMarkdown,
  previewAgentApproval,
  previewAgentScope,
  searchAgentThreads,
  updateAgentThreadSettings,
  type AgentScopeSummary,
  type AgentThreadSearchHit,
  type ApprovalPreview,
} from '../api/client'
import { useWorkspaces } from '../api/queries'
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
  const [saved, setSaved] = useState<string | null>(null)

  /** 当前选择 → 会话设置载荷（保存与 N151 范围预览共用一份口径）。 */
  function buildPayload() {
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
    }
  }

  const save = useMutation({
    mutationFn: () => updateAgentThreadSettings(threadId, buildPayload()),
    onSuccess: () => setSaved('已保存（下一轮对话生效）。'),
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
  }, [open, scopeWorkspace, toolMode, allowedTools, maxOps])
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
            <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
              设置在本轮结束后生效（下一轮读取）；进行中的回合不受影响。
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
