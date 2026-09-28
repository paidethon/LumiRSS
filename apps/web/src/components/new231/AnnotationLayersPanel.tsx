/** NEW-234 个人批注层 — 层 CRUD / 把选中批注加入层 / 按层读取（切换）/
 * 按层单独导出。层是纯个人结构，默认不混入共享面。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  assignAnnotationLayer,
  createAnnotationLayer,
  deleteAnnotationLayer,
  exportAnnotationLayer,
  layerAnnotations,
  listAnnotationLayers,
} from '../../api/new231'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

export function AnnotationLayersPanel({ selectedIds }: { selectedIds: Set<string> }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [activeLayerId, setActiveLayerId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const layers = useQuery({
    queryKey: ['new231-annotation-layers'],
    queryFn: ({ signal }) => listAnnotationLayers(signal),
  })
  const members = useQuery({
    queryKey: ['new231-annotation-layers', activeLayerId, 'annotations'],
    queryFn: ({ signal }) => layerAnnotations(activeLayerId ?? '', signal),
    enabled: activeLayerId !== null,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new231-annotation-layers'] })
  }

  const createMutation = useMutation({
    mutationFn: () => createAnnotationLayer(name.trim()),
    onSuccess: async (layer) => {
      setName('')
      setActiveLayerId(layer.id)
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '创建失败'),
  })
  const assignMutation = useMutation({
    mutationFn: () => assignAnnotationLayer(activeLayerId ?? '', [...selectedIds]),
    onSuccess: async (result) => {
      setNotice(
        result.skipped.length > 0
          ? `已加入 ${result.added.length} 条；${result.skipped.length} 条跳过。`
          : `已加入 ${result.added.length} 条。`,
      )
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '加入失败'),
  })
  const exportMutation = useMutation({
    mutationFn: () => exportAnnotationLayer(activeLayerId ?? '', true),
    onSuccess: async (markdown) => {
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'lumi-annotation-layer.md'
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice('已导出该层 Markdown。')
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '导出失败'),
  })
  const deleteMutation = useMutation({
    mutationFn: (layerId: string) => deleteAnnotationLayer(layerId),
    onSuccess: async (_result, layerId) => {
      if (activeLayerId === layerId) setActiveLayerId(null)
      setNotice('层已删除；层内批注回到未分层（本体保留）。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '删除失败'),
  })

  const layerItems = layers.data?.items ?? []

  return (
    <section aria-label="个人批注层（NEW-234）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">批注层</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-234 · 纯个人，默认不入共享面</span>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="新层名称（如：精读考据）"
          aria-label="新层名称"
          className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm"
        />
        <Button size="sm" variant="secondary" disabled={name.trim() === '' || createMutation.isPending} onClick={() => createMutation.mutate()}>
          创建层
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={activeLayerId === null || selectedIds.size === 0 || assignMutation.isPending}
          onClick={() => assignMutation.mutate()}
        >
          选中批注加入层（{selectedIds.size}）
        </Button>
      </div>

      {layers.isPending && <Skeleton className="h-12 w-full" />}
      {layers.isError && (
        <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">层加载失败。</div>
      )}
      {!layers.isPending && layerItems.length === 0 && !layers.isError && (
        <EmptyState title="还没有批注层" description="按用途分层（如「考据」「待办」），可切换读取与单独导出。" />
      )}

      {layerItems.length > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label="层列表">
          {layerItems.map((layer) => (
            <li key={layer.id} className="flex items-center gap-1">
              <Button
                size="sm"
                variant={activeLayerId === layer.id ? 'primary' : 'ghost'}
                onClick={() => setActiveLayerId(layer.id)}
                aria-pressed={activeLayerId === layer.id}
              >
                {layer.name}（{layer.itemCount}）
              </Button>
              <Button size="sm" variant="ghost" aria-label={`删除层 ${layer.name}`} disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate(layer.id)}>
                删
              </Button>
            </li>
          ))}
        </ul>
      )}

      {activeLayerId !== null && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <p className="text-xs text-[var(--lumi-text-secondary)]" aria-label="层内批注数">
              层内 {members.data?.items.length ?? 0} 条
            </p>
            <Button size="sm" variant="secondary" disabled={exportMutation.isPending} onClick={() => exportMutation.mutate()}>
              单独导出该层
            </Button>
          </div>
          <ul className="flex flex-col gap-1" aria-label="层内批注">
            {(members.data?.items ?? []).map((item) => (
              <li key={item.id} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                「{item.excerpt || '（无摘录）'}」{item.note ? ` — ${item.note}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
