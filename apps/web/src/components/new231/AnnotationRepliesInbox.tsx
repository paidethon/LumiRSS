/** NEW-236 批注回复提醒（收件人提醒箱）— 只覆盖明确共享的批注。
 * 收件人可查看原上下文（查看即清未读）、串内回复、关闭该串提醒；
 * 历史串用「含已关闭」查看。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addThreadReply,
  dismissThread,
  replyInbox,
  replyThreadDetail,
} from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

export function AnnotationRepliesInbox() {
  const queryClient = useQueryClient()
  const [includeDismissed, setIncludeDismissed] = useState(false)
  const [openThreadId, setOpenThreadId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const inbox = useQuery({
    queryKey: ['new231-reply-inbox', includeDismissed],
    queryFn: ({ signal }) => replyInbox(includeDismissed, signal),
  })
  const thread = useQuery({
    queryKey: ['new231-reply-thread', openThreadId],
    queryFn: ({ signal }) => replyThreadDetail(openThreadId ?? '', signal),
    enabled: openThreadId !== null,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new231-reply-inbox'] })
    await queryClient.invalidateQueries({ queryKey: ['new231-reply-thread'] })
  }

  const replyMutation = useMutation({
    mutationFn: () => addThreadReply(openThreadId ?? '', draft.trim()),
    onSuccess: async () => {
      setDraft('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '回复失败'),
  })
  const dismissMutation = useMutation({
    mutationFn: (threadId: string) => dismissThread(threadId),
    onSuccess: async () => {
      setOpenThreadId(null)
      setNotice('已关闭该串提醒。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '关闭失败'),
  })

  const items = inbox.data?.items ?? []

  return (
    <section aria-label="批注回复提醒（NEW-236）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">批注回复提醒</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-236 · 仅限明确共享的批注</span>
        <label className="ml-auto flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={includeDismissed}
            onChange={(event) => setIncludeDismissed(event.target.checked)}
            aria-label="包含已关闭的提醒"
            className="size-3.5"
          />
          含已关闭
        </label>
      </div>

      {inbox.isPending && <Skeleton className="h-12 w-full" />}
      {inbox.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">提醒箱加载失败。</div>
      )}
      {!inbox.isPending && items.length === 0 && !inbox.isError && (
        <EmptyState title="暂无共享批注提醒" description="他人明确共享给你的批注会出现在这里（含原上下文）。" />
      )}

      <ul className="flex flex-col gap-1" aria-label="提醒列表">
        {items.map((item) => (
          <li key={item.id} className="flex items-start gap-2 text-xs">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[var(--lumi-text-primary)]">
                {item.unreadForRecipient > 0 ? `【${item.unreadForRecipient} 条未读】` : ''}
                「{item.excerpt || '（无摘录）'}」
              </p>
              <p className="text-[var(--lumi-text-tertiary)]">
                {item.replyCount} 条回复{item.dismissedAt ? ' · 已关闭' : ''}
              </p>
            </div>
            <Button size="sm" variant="secondary" onClick={() => setOpenThreadId(item.id)}>
              查看原上下文
            </Button>
            {!item.dismissedAt && (
              <Button size="sm" variant="ghost" disabled={dismissMutation.isPending} onClick={() => dismissMutation.mutate(item.id)}>
                关闭提醒
              </Button>
            )}
          </li>
        ))}
      </ul>

      {openThreadId !== null && thread.data && (
        <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2" aria-label="共享串详情">
          <p className="text-xs text-[var(--lumi-text-primary)]">
            原文摘录：「{thread.data.excerpt || '（无摘录）'}」
          </p>
          {thread.data.note && <p className="text-xs text-[var(--lumi-text-secondary)]">共享时批注：{thread.data.note}</p>}
          <ul className="flex flex-col gap-1" aria-label="回复列表">
            {(thread.data.replies ?? []).map((reply) => (
              <li key={reply.id} className="text-xs text-[var(--lumi-text-secondary)]">
                {reply.authorUsername}：{reply.body}
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="回复…"
              aria-label="回复内容"
              className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
            />
            <Button size="sm" variant="primary" disabled={draft.trim() === '' || replyMutation.isPending} onClick={() => replyMutation.mutate()}>
              回复
            </Button>
          </div>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
