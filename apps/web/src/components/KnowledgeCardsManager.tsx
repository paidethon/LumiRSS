/** KnowledgeCardsManager — F070 书签页「知识卡片」页签。
 *
 * 检索（concept/explanation）+ 列表（含原文标题/stale 标注）+
 * 跳原文（打开 entryRef）+ 删除 + N076 加入复习（知识卡片走与批注
 * 相同的到期/揭示复习流程）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, Search, Trash2 } from 'lucide-react'
import {
  addReviewQueueItem,
  deleteKnowledgeCard,
  listKnowledgeCards,
} from '../api/client'
import { useReaderUi } from '../store/reader-ui'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

export function KnowledgeCardsManager() {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [reviewInfo, setReviewInfo] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const selectEntry = useReaderUi((s) => s.selectEntry)

  const cardsQuery = useQuery({
    queryKey: ['knowledge-cards', debounced],
    queryFn: () => listKnowledgeCards(debounced),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteKnowledgeCard(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['knowledge-cards'] })
    },
  })
  // N076：加入复习 —— 立即到期；已在队列中（409）诚实提示。
  const addToReview = useMutation({
    mutationFn: (cardId: string) =>
      addReviewQueueItem({
        kind: 'knowledge_card',
        knowledgeCardId: cardId,
        dueAt: new Date().toISOString(),
      }),
    onSuccess: async () => {
      setReviewInfo('已加入复习（书签页「批注」→「复习」）。')
      await queryClient.invalidateQueries({ queryKey: ['review-queue-manager'] })
    },
    onError: (error) =>
      setReviewInfo(error instanceof Error ? error.message : '加入复习失败'),
  })

  const items = cardsQuery.data?.items ?? []

  return (
    <div className="flex flex-col gap-3" data-lumi-knowledge-manager="">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-52 flex-1 items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2">
          <Search aria-hidden className="size-3.5 text-[var(--lumi-text-tertiary)]" />
          <input
            aria-label="检索知识卡片"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') setDebounced(query)
            }}
            onBlur={() => setDebounced(query)}
            placeholder="检索概念/解释…"
            className="min-h-9 w-full bg-transparent text-sm text-[var(--lumi-text-primary)] focus:outline-none"
          />
        </div>
        <Button size="sm" variant="secondary" onClick={() => setDebounced(query)}>
          检索
        </Button>
      </div>

      {cardsQuery.isPending && (
        <div className="flex flex-col gap-2" aria-label="知识卡片加载中">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-4/5" />
        </div>
      )}
      {cardsQuery.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          知识卡片加载失败。
          <Button size="sm" variant="ghost" onClick={() => cardsQuery.refetch()}>
            重试
          </Button>
        </p>
      )}
      {!cardsQuery.isPending && !cardsQuery.isError && items.length === 0 && (
        <EmptyState
          title="还没有知识卡片"
          description="在阅读文章时点击「知识卡片」即可提取并保存概念卡。"
        />
      )}

      {reviewInfo !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{reviewInfo}</p>
      )}
      <ul className="flex flex-col gap-2">
        {items.map((card) => (
          <li
            key={card.id}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{card.concept}</span>
              {card.stale && (
                <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                  原文已删除
                </span>
              )}
              <span className="flex-1" />
              {!card.stale && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => selectEntry(card.entryRef)}
                >
                  跳原文
                </Button>
              )}
              <Button
                size="sm"
                variant="secondary"
                disabled={addToReview.isPending}
                onClick={() => addToReview.mutate(card.id)}
              >
                <CalendarPlus aria-hidden className="size-3.5" />
                加入复习
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate(card.id)}
              >
                <Trash2 aria-hidden className="size-3.5" />
                删除
              </Button>
            </div>
            <p className="mt-1 text-[var(--lumi-text-secondary)]">{card.explanation}</p>
            {card.sourceQuote !== '' && (
              <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                引文：“{card.sourceQuote}”
                {card.quoteVerified ? '' : '（未核验）'}
              </p>
            )}
            {card.entryTitle !== null && (
              <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">来源：{card.entryTitle}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
