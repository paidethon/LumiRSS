/** AnnotationBasketsPanel — N072 批注精选篮（BookmarksPage「批注」页签）。
 *
 * 创建/选择篮 → 从批注列表多选「加入篮」→ 篮内逐项回跳原文（deep
 * link，broken 诚实标注「原文已变化/已删除」）→ 按篮导出（复用既有
 * export 路径，basketId 过滤）→ 移除/删除篮。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Download, Plus, Trash2 } from 'lucide-react'
import {
  addAnnotationBasketItems,
  createAnnotationBasket,
  deleteAnnotationBasket,
  exportAnnotations,
  listAnnotationBasketItems,
  listAnnotationBaskets,
  removeAnnotationBasketItem,
} from '../api/client'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

export function AnnotationBasketsPanel({ selectedIds }: { selectedIds: Set<string> }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [activeBasketId, setActiveBasketId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const basketsQuery = useQuery({
    queryKey: ['annotation-baskets'],
    queryFn: ({ signal }) => listAnnotationBaskets(signal),
  })
  const itemsQuery = useQuery({
    queryKey: ['annotation-baskets', activeBasketId, 'items'],
    queryFn: ({ signal }) => listAnnotationBasketItems(activeBasketId ?? '', signal),
    enabled: activeBasketId !== null,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['annotation-baskets'] })
    await queryClient.invalidateQueries({ queryKey: ['annotations-manager'] })
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      const basket = await createAnnotationBasket(name.trim())
      setName('')
      return basket
    },
    onSuccess: async (basket) => {
      setActiveBasketId(basket.id)
      await invalidate()
    },
    onError: (error) =>
      setNotice(error instanceof Error ? error.message : '创建失败'),
  })
  const addMutation = useMutation({
    mutationFn: (ids: string[]) => addAnnotationBasketItems(activeBasketId ?? '', ids),
    onSuccess: async (result) => {
      setNotice(
        result.added.length > 0
          ? `已加入 ${result.added.length} 条${result.skipped.length > 0 ? `（${result.skipped.length} 条跳过）` : ''}`
          : '没有可加入的批注（所选批注不在篮中变化）',
      )
      await invalidate()
    },
  })
  const removeMutation = useMutation({
    mutationFn: (annotationId: string) => removeAnnotationBasketItem(activeBasketId ?? '', annotationId),
    onSuccess: async () => {
      await invalidate()
      await queryClient.invalidateQueries({ queryKey: ['annotation-baskets', activeBasketId, 'items'] })
    },
  })
  const deleteBasketMutation = useMutation({
    mutationFn: (basketId: string) => deleteAnnotationBasket(basketId),
    onSuccess: async () => {
      setActiveBasketId(null)
      await invalidate()
    },
  })
  const exportMutation = useMutation({
    mutationFn: () => exportAnnotations({ basketId: activeBasketId ?? undefined }),
    onSuccess: async (blob) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'lumi-annotations-basket.md'
      anchor.click()
      URL.revokeObjectURL(url)
    },
    onError: (error) =>
      setNotice(error instanceof Error ? `导出失败：${error.message}` : '导出失败'),
  })

  const baskets = basketsQuery.data?.items ?? []
  const items = itemsQuery.data?.items ?? []

  return (
    <section
      aria-label="批注精选篮"
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">精选篮</h3>
        <span className="flex-1" />
        {selectedIds.size > 0 && activeBasketId !== null && (
          <Button
            size="sm"
            variant="secondary"
            disabled={addMutation.isPending}
            onClick={() => addMutation.mutate([...selectedIds])}
          >
            <Plus aria-hidden className="size-3.5" />
            加入所选（{selectedIds.size}）
          </Button>
        )}
        {activeBasketId !== null && (
          <Button
            size="sm"
            variant="secondary"
            disabled={exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            <Download aria-hidden className="size-3.5" />
            导出此篮
          </Button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {basketsQuery.isPending && <Skeleton className="h-7 w-40" />}
          {baskets.map((basket) => (
            <button
              key={basket.id}
              type="button"
              aria-pressed={basket.id === activeBasketId}
              onClick={() => setActiveBasketId(basket.id)}
              className={cx(
                'rounded-[var(--lumi-radius-md)] border px-2 py-1 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
                basket.id === activeBasketId
                  ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                  : 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              {basket.name}（{basket.itemCount}）
            </button>
          ))}
        </div>
        {activeBasketId !== null && (
          <Button
            size="sm"
            variant="ghost"
            className="text-[var(--lumi-danger, #dc2626)]"
            onClick={() => deleteBasketMutation.mutate(activeBasketId)}
          >
            <Trash2 aria-hidden className="size-3.5" /> 删除此篮
          </Button>
        )}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && name.trim() !== '') createMutation.mutate()
          }}
          placeholder="新篮名称"
          aria-label="新篮名称"
          className="w-44 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs text-[var(--lumi-text-primary)]"
        />
        <Button
          size="sm"
          variant="ghost"
          disabled={name.trim() === '' || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          创建
        </Button>
      </div>
      {notice !== null && (
        <p role="status" className="mt-1.5 text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}

      {activeBasketId !== null && (
        <div className="mt-2">
          {itemsQuery.isPending && <Skeleton className="h-10 w-full" />}
          {itemsQuery.isError && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">篮内容加载失败</p>
          )}
          {itemsQuery.isSuccess && items.length === 0 && (
            <EmptyState
              title="篮是空的"
              description="在下方批注列表勾选后点「加入所选」。"
            />
          )}
          <ul className="flex flex-col gap-1.5">
            {items.map((item) => (
              <li
                key={item.annotationId}
                className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
              >
                {item.broken && item.annotation === null ? (
                  <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px]">
                    已删除
                  </span>
                ) : item.broken ? (
                  <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px]">
                    原文已变化
                  </span>
                ) : null}
                <span className="min-w-0 flex-1 truncate">
                  {item.annotation
                    ? item.annotation.excerpt !== ''
                      ? item.annotation.excerpt
                      : item.annotation.note
                    : item.annotationId}
                </span>
                {item.annotation != null && !item.broken && (
                  <a
                    href={`/reader?entry=${encodeURIComponent(item.annotation.entryRef)}&para=${encodeURIComponent(
                      String(item.annotation.anchor.paraId ?? ''),
                    )}`}
                    className="text-[var(--lumi-accent)] hover:underline"
                    aria-label="跳回原文定位"
                  >
                    回跳
                  </a>
                )}
                <button
                  type="button"
                  aria-label="移出精选篮"
                  onClick={() => removeMutation.mutate(item.annotationId)}
                  className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
