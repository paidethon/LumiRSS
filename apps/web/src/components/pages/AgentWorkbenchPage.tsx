/** AgentWorkbenchPage — phase2 G7：Agent 工作台。
 *
 * App 已把本页接入 section='agent'（桌面 Timeline 列位 + 移动 section 区）。
 *
 * - 左：会话列表（新会话 POST /agent/threads；行 = 标题 + 相对时间 +
 *   删除 IconButton）；右：消息区。
 * - 消息按 role 渲染：user 右侧气泡 / assistant 纯文本 / tool 紧凑
 *   等宽卡片（前缀 工具）/ approval 显著卡片（tool + args pretty JSON，
 *   pending 时给 批准/拒绝 按钮）。citations 以小字随 assistant 展示。
 * - 发送：POST messages（202 processing）→ 轮询 /messages（queries 里
 *   refetchInterval：最新 role 为 assistant / approval 时停止）。
 *   服务端异步跑完本轮；轮询是最鲁棒的读回方式（SSE 仅是优化路径，
 *   v1 不引入 EventSource 重订阅复杂度）。
 * - 未配置 AI provider 会以 assistant 消息出现（text 以 处理失败 /
 *   AI 未配置 开头）——原样作为普通 assistant 消息渲染（诚实呈现）。
 * - loading / empty / error 三态齐备；所有 HTTP 经 src/api/client.ts。
 * - 无 assistant-ui 之类的库：全部普通组件 + Lumi primitives。 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Bot, Plus, Trash2 } from 'lucide-react'
import {
  useAgentApprovalMutation,
  useAgentMessages,
  useAgentThreads,
  useCreateAgentThreadMutation,
  useDeleteAgentThreadMutation,
  useRagStatus,
  useSendAgentMessageMutation,
} from '../../api/queries'
import type { AgentApprovalContent, AgentMessage } from '../../api/client'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-10 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

/** ISO 时间戳 → 相对时间；无效回退「从未」。 */
function formatRelative(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '从未'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return `${days} 天前`
}

/** content.text 容错提取（契约是 {text: string}，防御异常形状）。 */
function textOf(content: Record<string, unknown>): string {
  const text = content['text']
  return typeof text === 'string' ? text : ''
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

/** RAG 状态 chip（只读展示；启用/未启用/不可用三态，诚实呈现）。 */
function RagStatusChip() {
  const status = useRagStatus()
  if (status.isPending || status.isError || status.data === undefined) {
    return null
  }
  const data = status.data
  const label = data.enabled
    ? `语义检索已启用 · ${data.chunks} 块`
    : data.fastembedAvailable
      ? '语义检索未启用'
      : '语义检索不可用（fastembed 未安装）'
  return (
    <span
      role="status"
      title={data.lastError !== null && data.lastError !== '' ? `上次错误：${data.lastError}` : undefined}
      className={cx(
        'ml-auto shrink-0 rounded-[var(--lumi-radius-full)] border px-2 py-0.5 text-[11px]',
        data.enabled
          ? 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)]'
          : 'border-[var(--lumi-border)] text-[var(--lumi-text-tertiary)]',
      )}
    >
      {label}
    </span>
  )
}

/** 单条消息：按 role 分派渲染。 */
function MessageRow({ message }: { message: AgentMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-[var(--lumi-radius-lg)] bg-[var(--lumi-accent-soft)] px-3 py-2 text-sm whitespace-pre-wrap text-[var(--lumi-text-primary)]">
          {textOf(message.content)}
        </div>
      </div>
    )
  }

  if (message.role === 'tool') {
    const name = typeof message.content['name'] === 'string' ? message.content['name'] : ''
    const result = 'result' in message.content ? message.content['result'] : message.content
    return (
      <div className="max-w-[95%] self-start rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
        <p className="text-[11px] font-medium text-[var(--lumi-text-tertiary)]">
          工具{name !== '' ? ` · ${name}` : ''}
        </p>
        <pre className="mt-1 overflow-x-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-[var(--lumi-text-secondary)]">
          {prettyJson(result)}
        </pre>
      </div>
    )
  }

  if (message.role === 'system') {
    return (
      <p className="self-center text-center text-xs text-[var(--lumi-text-tertiary)]">
        {textOf(message.content)}
      </p>
    )
  }

  if (message.role === 'approval') {
    return <ApprovalCard message={message} />
  }

  // assistant：纯文本（含 处理失败 / AI 未配置 的诚实失败消息——原样展示）。
  return (
    <div className="max-w-[95%] self-start">
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-[var(--lumi-text-primary)]">
        {textOf(message.content)}
      </p>
      {message.citations.length > 0 && (
        <p className="mt-1 text-[11px] break-all text-[var(--lumi-text-tertiary)]">
          引用：{message.citations.join('、')}
        </p>
      )}
    </div>
  )
}

/** content → approval 字段容错读取（契约形状异常时不崩溃）。 */
function approvalOf(content: Record<string, unknown>): AgentApprovalContent {
  const args = content['args']
  return {
    approvalId: String(content['approvalId'] ?? ''),
    callId: String(content['callId'] ?? ''),
    tool: String(content['tool'] ?? ''),
    args:
      args !== null && typeof args === 'object'
        ? (args as Record<string, unknown>)
        : {},
    status: String(content['status'] ?? ''),
  }
}

/** approval 显著卡片：tool + args pretty JSON + 批准/拒绝（pending 时）。 */
function ApprovalCard({ message }: { message: AgentMessage }) {
  const approval = approvalOf(message.content)
  const decide = useAgentApprovalMutation(message.threadId)
  const pending = approval.status === 'pending'

  return (
    <div
      className={cx(
        'w-full max-w-[95%] self-start rounded-[var(--lumi-radius-lg)] border px-3 py-2.5',
        pending
          ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)]'
          : 'border-[var(--lumi-border)]',
      )}
      aria-label="写操作批准请求"
    >
      <p className="text-xs font-semibold text-[var(--lumi-text-primary)]">
        需要批准的写入操作 · {approval.tool}
      </p>
      <pre className="mt-1.5 overflow-x-auto rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1.5 font-mono text-[11px] leading-relaxed text-[var(--lumi-text-secondary)]">
        {prettyJson(approval.args)}
      </pre>
      {pending ? (
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            variant="primary"
            aria-label="批准写入"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ approvalId: approval.approvalId, decision: 'approve' })}
          >
            批准
          </Button>
          <Button
            size="sm"
            variant="secondary"
            aria-label="拒绝写入"
            disabled={decide.isPending}
            onClick={() => decide.mutate({ approvalId: approval.approvalId, decision: 'reject' })}
          >
            拒绝
          </Button>
        </div>
      ) : (
        <p className="mt-1.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          {approval.status === 'approved' ? '已批准' : approval.status === 'rejected' ? '已拒绝' : `状态：${approval.status}`}
        </p>
      )}
      {decide.isError && (
        <p role="alert" className="mt-1.5 text-[11px] text-[var(--lumi-danger)]">
          {decide.error.message}
        </p>
      )}
    </div>
  )
}

/** 消息区（含发送框）。空会话给 能力说明 + 示例问题。 */
function ChatArea({ threadId, title }: { threadId: string; title: string }) {
  const messages = useAgentMessages(threadId)
  const send = useSendAgentMessageMutation(threadId)
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const items = messages.data?.items ?? []
  const processing =
    send.isPending ||
    (items.length > 0 &&
      items[items.length - 1].role !== 'assistant' &&
      items[items.length - 1].role !== 'approval')

  // 新消息到达时滚到底部（消息数量变化才触发，不打扰滚动回看）。
  useEffect(() => {
    if (typeof bottomRef.current?.scrollIntoView === 'function') {
      bottomRef.current.scrollIntoView({ block: 'end' })
    }
  }, [items.length])

  const submit = () => {
    const text = draft.trim()
    if (text === '' || send.isPending) return
    send.mutate(text, { onSuccess: () => setDraft('') })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-[var(--lumi-separator)] px-3 py-2">
        <h2 className="min-w-0 truncate text-sm font-semibold text-[var(--lumi-text-primary)]">
          {title}
        </h2>
        <RagStatusChip />
      </div>

      <div
        role="log"
        aria-live="polite"
        aria-label="消息记录"
        className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto p-3 max-lg:pb-[76px]"
      >
        {messages.isPending && (
          <div className="flex flex-col gap-2" aria-label="消息加载中">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-10 w-4/5" />
          </div>
        )}

        {messages.isError && (
          <div role="alert" className="flex flex-col items-start gap-1.5 p-2 text-sm text-[var(--lumi-danger)]">
            <p className="flex items-center gap-1.5">
              <AlertCircle aria-hidden className="size-3.5 shrink-0" />
              {messages.error.message}
            </p>
            <Button size="sm" variant="secondary" onClick={() => messages.refetch()}>
              重试
            </Button>
          </div>
        )}

        {!messages.isPending && !messages.isError && items.length === 0 && (
          <div className="mt-6">
            <EmptyState
              icon={<Bot aria-hidden className="size-8" />}
              title="还没有消息，发第一条试试"
              description="可以问关于订阅、书签、剪藏与工作区的问题；涉及写入的操作会先请求批准。语义检索启用后，回答会引用库内内容。"
            />
            <div className="mx-auto max-w-sm px-2">
              <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">示例问题</p>
              <ul className="mt-1.5 flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
                <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
                  我的稍后读里有哪些文章？
                </li>
                <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
                  把这篇加到「稍后读」工作区
                </li>
                <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
                  库里关于「阅读器」的笔记有哪些？
                </li>
              </ul>
            </div>
          </div>
        )}

        {items.map((message) => (
          <MessageRow key={message.id} message={message} />
        ))}
        <div ref={bottomRef} aria-hidden="true" />
        {processing && (
          <p role="status" className="self-start text-xs text-[var(--lumi-text-tertiary)]">
            正在处理…
          </p>
        )}
      </div>

      <div className="border-t border-[var(--lumi-separator)] p-3">
        {send.isError && (
          <p role="alert" className="mb-1.5 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="size-3.5 shrink-0" />
            {send.error.message}
          </p>
        )}
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
            }}
            placeholder="输入消息…"
            aria-label="输入消息"
            className={inputCls}
          />
          <Button size="md" variant="primary" onClick={submit} disabled={draft.trim() === '' || send.isPending}>
            发送
          </Button>
        </div>
      </div>
    </div>
  )
}

/** 无会话：能力说明 + 示例问题 + 新会话引导。 */
function NoThreadPlaceholder() {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <EmptyState
          icon={<Bot aria-hidden className="size-10" />}
          title="还没会话，点新会话开始…"
          description="Agent 可以检索你的订阅、书签、剪藏与工作区并回答问题；写入操作（如保存书签、加入工作区）需要逐条批准后才会执行。"
        />
        <div className="mx-auto max-w-sm px-2 pb-2">
          <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">示例问题</p>
          <ul className="mt-1.5 flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
            <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
              我的稍后读里有哪些文章？
            </li>
            <li className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5">
              总结最近收藏的内容
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}

/** 会话列表（左侧栏）。 */
function ThreadList({
  activeId,
  onSelect,
}: {
  activeId: string | null
  onSelect: (threadId: string) => void
}) {
  const threads = useAgentThreads()
  const create = useCreateAgentThreadMutation()
  const remove = useDeleteAgentThreadMutation()

  const items = useMemo(() => threads.data?.items ?? [], [threads.data])

  return (
    <aside
      aria-label="会话列表"
      className={cx(
        'flex w-full shrink-0 flex-col border-b border-[var(--lumi-separator)]',
        'lg:w-56 lg:border-r lg:border-b-0',
      )}
    >
      <div className="flex items-center gap-2 px-2.5 py-2">
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">会话</h2>
        <Button
          size="sm"
          variant="primary"
          className="ml-auto"
          onClick={() => create.mutate()}
          disabled={create.isPending}
        >
          <Plus aria-hidden className="size-3.5" />
          新会话
        </Button>
      </div>

      {create.isError && (
        <p role="alert" className="px-2.5 pb-1 text-xs text-[var(--lumi-danger)]">
          {create.error.message}
        </p>
      )}
      {remove.isError && (
        <p role="alert" className="px-2.5 pb-1 text-xs text-[var(--lumi-danger)]">
          {remove.error.message}
        </p>
      )}

      {threads.isPending && (
        <div className="flex flex-col gap-1.5 px-2.5 pb-2" aria-label="会话加载中">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      )}

      {threads.isError && (
        <div role="alert" className="flex flex-col items-start gap-1.5 px-2.5 pb-2 text-sm text-[var(--lumi-danger)]">
          <p>会话列表加载失败</p>
          <Button size="sm" variant="secondary" onClick={() => threads.refetch()}>
            重试
          </Button>
        </div>
      )}

      {threads.data !== undefined && items.length === 0 && (
        <p className="px-2.5 pb-2 text-xs text-[var(--lumi-text-tertiary)]">还没有会话</p>
      )}

      <ul className="flex flex-col gap-0.5 overflow-y-auto px-1.5 pb-2">
        {items.map((thread) => (
          <li key={thread.id} className="group flex items-center gap-1">
            <button
              type="button"
              onClick={() => onSelect(thread.id)}
              aria-current={activeId === thread.id ? 'true' : undefined}
              className={cx(
                'flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-left',
                'min-h-11 transition-colors duration-[var(--lumi-motion-fast)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                activeId === thread.id
                  ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-accent-text)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
              )}
            >
              <span className="w-full truncate text-sm" title={thread.title}>
                {thread.title}
              </span>
              <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
                {formatRelative(thread.createdAt)}
              </span>
            </button>
            <IconButton
              icon={<Trash2 aria-hidden className="size-4" />}
              label="删除会话"
              size="sm"
              touch
              disabled={remove.isPending}
              onClick={() => remove.mutate(thread.id)}
              className="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 max-lg:opacity-100"
            />
          </li>
        ))}
      </ul>
    </aside>
  )
}

/** 页面根：左会话列表 + 右消息区。 */
export default function AgentWorkbenchPage() {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const threads = useAgentThreads()
  const items = threads.data?.items ?? []
  const activeThread =
    activeThreadId !== null ? (items.find((t) => t.id === activeThreadId) ?? null) : null

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col lg:flex-row">
      <ThreadList activeId={activeThreadId} onSelect={setActiveThreadId} />
      {activeThread !== null ? (
        <ChatArea threadId={activeThread.id} title={activeThread.title} />
      ) : (
        <NoThreadPlaceholder />
      )}
    </div>
  )
}
