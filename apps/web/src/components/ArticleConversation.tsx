/** ArticleConversation — 0016：文章限定的 AI 对话面板。
 *
 * 桌面 = 右侧面板（Sheet side="right"）；移动端 = 全宽全屏对话表面。
 * 底层 Reader 状态不受影响：面板是 fixed overlay，关闭后文章原样保留。
 *
 * 行为：
 * - 打开即读消息存储（GET 只读，零 provider 调用）；reopen 恢复历史；
 * - 提交问题 = 一次有界 provider 调用（非流式）；成功后问题 + 回答
 *   持久化并写回 query cache；
 * - 失败：输入内容保留，错误内联提示，直接再点发送即可重试；
 * - Escape / 遮罩点击 / ✕ 关闭（Sheet 原语，含焦点 trap 与还焦）。
 *
 * 安全：消息纯文本渲染（whitespace-pre-wrap），永不进 HTML 渲染路径。
 */

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Loader2, MessageSquare, RefreshCw, SendHorizontal, X } from 'lucide-react'
import type { ConversationMessage } from '../api/types'
import { useEntryConversation, useSendConversationMessageMutation } from '../api/queries'
import { ApiError } from '../api/client'
import { Button } from './ui/Button'
import { IconButton } from './ui/IconButton'
import { Skeleton } from './ui/Skeleton'
import { Sheet } from './ui/Sheet'
import { cx } from './ui/cx'

const FAILURE_TEXT: Record<string, string> = {
  auth_error: 'API 密钥被服务端拒绝，请检查服务端的 AI_API_KEY 配置。',
  model_error: '模型或接口地址不存在，请检查 AI 设置中的 Base URL 与 Model。',
  rate_limited: 'AI 服务请求过于频繁，请稍后再试。',
  timeout: 'AI 服务响应超时，请重试。',
  invalid_response: 'AI 服务返回了无法解析的结果，请重试。',
  upstream_error: 'AI 服务暂时不可用，请稍后再试。',
  not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  ai_not_configured: 'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
}

function failureText(error: unknown): string {
  if (error instanceof ApiError) {
    // BFF 错误信封类型带 ai_ 前缀（ai_rate_limited），缓存 failureType
    // 不带——两种都按同一稳定文案查找。
    const known =
      FAILURE_TEXT[error.type] ??
      FAILURE_TEXT[error.type.replace(/^ai_/, '')]
    if (known !== undefined) {
      return known
    }
  }
  return error instanceof Error ? error.message : '发送失败，请重试。'
}

function MessageBubble({ message }: { message: ConversationMessage }) {
  const isUser = message.role === 'user'
  return (
    <div className={cx('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cx(
          'max-w-[85%] whitespace-pre-wrap rounded-[var(--lumi-radius-lg)] px-3 py-2 text-sm leading-relaxed',
          isUser
            ? 'bg-[var(--lumi-accent)] text-[var(--lumi-on-accent, #fff)]'
            : 'border border-[var(--lumi-border)] bg-[var(--lumi-surface)] text-[var(--lumi-text-primary)]',
        )}
      >
        {message.content}
      </div>
    </div>
  )
}

export default function ArticleConversation({
  entryRef,
  articleTitle,
  open,
  onClose,
}: {
  entryRef: string
  articleTitle: string
  open: boolean
  onClose: () => void
}) {
  const conversation = useEntryConversation(entryRef, open)
  const send = useSendConversationMessageMutation(entryRef)
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // 新消息（含打开时恢复的历史）→ 滚动到底部。
  useEffect(() => {
    const el = scrollRef.current
    if (el !== null) {
      el.scrollTop = el.scrollHeight
    }
  }, [conversation.data?.messages.length, open, send.isPending])

  const canSend = draft.trim() !== '' && !send.isPending

  const submit = () => {
    if (!canSend) {
      return
    }
    // 失败时 draft 保留（清空只发生在成功回调），用户可直接重发。
    send.mutate(draft, { onSuccess: () => setDraft('') })
  }

  const messages = conversation.data?.messages ?? []

  return (
    <Sheet
      open={open}
      onClose={onClose}
      label="AI 对话"
      side="right"
      panelClassName="flex flex-col max-md:h-dvh"
    >
      {/* 头部：文章上下文 + 关闭 */}
      <header className="flex items-start justify-between gap-3 border-b border-[var(--lumi-border)] px-4 py-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
            <MessageSquare aria-hidden className="size-4 text-[var(--lumi-accent)]" />
            AI 对话
          </p>
          <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]" title={articleTitle}>
            针对：{articleTitle}
          </p>
        </div>
        <IconButton icon={<X aria-hidden />} label="关闭对话" onClick={onClose} />
      </header>

      {/* 消息区 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
        {conversation.isPending && (
          <div className="flex flex-col gap-3" aria-label="正在加载对话">
            <Skeleton className="h-9 w-4/5 self-start" />
            <Skeleton className="h-14 w-3/5 self-end" />
            <Skeleton className="h-9 w-3/4 self-start" />
          </div>
        )}

        {conversation.isError && (
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
            <p role="alert" className="flex items-start gap-1.5 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
              <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              {failureText(conversation.error)}
            </p>
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              onClick={() => conversation.refetch()}
            >
              <RefreshCw aria-hidden className="size-3.5" />
              重试
            </Button>
          </div>
        )}

        {!conversation.isPending && !conversation.isError && messages.length === 0 && (
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5">
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
              就当前文章提问
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              对话只基于这篇文章的内容。例如：
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              <li>· 这篇文章主要在说什么？</li>
              <li>· 作者为什么得出这个结论？</li>
              <li>· 根据本文列出三个关键观点。</li>
            </ul>
          </div>
        )}

        {!conversation.isPending && !conversation.isError && messages.length > 0 && (
          <div className="flex flex-col gap-3">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {send.isPending && (
              <div className="flex justify-start" role="status">
                <div className="flex items-center gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-secondary)]">
                  <Loader2 aria-hidden className="size-3.5 animate-spin" />
                  AI 正在思考…
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <form
        className="border-t border-[var(--lumi-border)] px-4 pt-3 pb-[max(0.75rem,var(--safe-bottom))]"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        {send.isError && (
          <p role="alert" className="mb-2 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {failureText(send.error)}
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Enter 发送，Shift+Enter 换行。
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            rows={2}
            maxLength={4000}
            aria-label="输入问题"
            placeholder="就这篇文章提问…"
            className={cx(
              'min-h-11 flex-1 resize-none rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
              'bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            )}
          />
          <Button
            type="submit"
            size="sm"
            className="min-h-11 shrink-0"
            disabled={!canSend}
            aria-label="发送"
          >
            {send.isPending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <SendHorizontal aria-hidden className="size-4" />
            )}
          </Button>
        </div>
      </form>
    </Sheet>
  )
}
