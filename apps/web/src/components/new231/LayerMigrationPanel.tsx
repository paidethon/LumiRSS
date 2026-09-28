/** NEW-238 标注批量迁移 — 指定标注从一个个人集合（层）迁入另一个。
 * 先预览（来源/标签变化，零写入），确认后应用；原文章身份不变。 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  applyLayerMigration,
  listAnnotationLayers,
  previewLayerMigration,
  type LayerMigrationPreview,
} from '../../api/new231'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

export function LayerMigrationPanel({ selectedIds }: { selectedIds: Set<string> }) {
  const [fromLayerId, setFromLayerId] = useState<string>('')
  const [toLayerId, setToLayerId] = useState<string>('')
  const [preview, setPreview] = useState<LayerMigrationPreview | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const layers = useQuery({
    queryKey: ['new231-annotation-layers'],
    queryFn: ({ signal }) => listAnnotationLayers(signal),
  })
  const layerItems = layers.data?.items ?? []

  const previewMutation = useMutation({
    mutationFn: () =>
      previewLayerMigration(
        fromLayerId === '' ? null : fromLayerId,
        toLayerId,
        selectedIds.size > 0 ? [...selectedIds] : undefined,
      ),
    onSuccess: (result) => setPreview(result),
    onError: (error) => setNotice(error instanceof Error ? error.message : '预览失败'),
  })
  const applyMutation = useMutation({
    mutationFn: () =>
      applyLayerMigration(
        fromLayerId === '' ? null : fromLayerId,
        toLayerId,
        selectedIds.size > 0 ? [...selectedIds] : undefined,
      ),
    onSuccess: async (result) => {
      setPreview(null)
      setNotice(`已迁移 ${result.count} 条；原文章身份未改动。`)
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '迁移失败'),
  })

  return (
    <section aria-label="标注批量迁移（NEW-238）" className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">批量迁移</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-238 · 层间迁移，文章身份不变</span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
        <label>
          来源
          <select
            aria-label="来源层"
            value={fromLayerId}
            onChange={(event) => setFromLayerId(event.target.value)}
            className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
          >
            <option value="">未分层</option>
            {layerItems.map((layer) => (
              <option key={layer.id} value={layer.id}>{layer.name}</option>
            ))}
          </select>
        </label>
        <label>
          目标
          <select
            aria-label="目标层"
            value={toLayerId}
            onChange={(event) => setToLayerId(event.target.value)}
            className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
          >
            <option value="">选择目标层…</option>
            {layerItems.map((layer) => (
              <option key={layer.id} value={layer.id}>{layer.name}</option>
            ))}
          </select>
        </label>
        {selectedIds.size > 0 && <span>（限定选中 {selectedIds.size} 条）</span>}
        <Button
          size="sm"
          variant="secondary"
          disabled={toLayerId === '' || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          预览迁移
        </Button>
      </div>

      {layers.isPending && <Skeleton className="h-8 w-full" />}

      {preview !== null && (
        <div className="flex flex-col gap-1" aria-label="迁移预览">
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            {preview.fromLayer ?? '未分层'} → {preview.toLayer}：{preview.count} 条（预览，未写入）
          </p>
          <ul className="flex flex-col gap-0.5">
            {preview.items.map((item) => (
              <li key={item.annotationId} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                「{item.excerpt || '（无摘录）'}」 · {item.fromLayer ?? '未分层'} → {item.toLayer}
              </li>
            ))}
          </ul>
          <div>
            <Button size="sm" variant="primary" disabled={applyMutation.isPending} onClick={() => applyMutation.mutate()}>
              确认迁移
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
