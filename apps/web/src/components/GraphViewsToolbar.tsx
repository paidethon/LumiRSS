/** GraphViewsToolbar — F076 图谱命名视图（GraphPage 工具栏）。
 *
 * 保存当前（名称输入；同名 → 确认覆盖重发 overwrite）→ 视图下拉
 * （恢复：应用位置到存在节点、新节点默认位、失效节点跳过；filters
 * 与 focus 一并恢复）→ 覆盖保存/删除。 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { deleteGraphView, listGraphViews, saveGraphView } from '../api/client'
import { applyGraphLayout, type GraphNodeLike } from '../lib/graph-views'
import { Button } from './ui/Button'

export function GraphViewsToolbar({
  nodes,
  filters,
  focusNode,
  captureLayout,
  onRestore,
}: {
  nodes: GraphNodeLike[]
  /** 当前筛选意图（随视图保存/恢复）。 */
  filters: Record<string, unknown>
  focusNode: string | null
  /** 捕获当前节点位置（画布模式可为空表——诚实仅存筛选/焦点）。 */
  captureLayout: () => Record<string, { x: number; y: number }>
  /** 恢复回调：应用位置 + filters + focus。 */
  onRestore: (payload: {
    layout: Record<string, { x: number; y: number }>
    filters: Record<string, unknown>
    focusNode: string | null
  }) => void
}) {
  const [name, setName] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const viewsQuery = useQuery({
    queryKey: ['graph-views'],
    queryFn: () => listGraphViews(),
  })
  const [overwriteArmed, setOverwriteArmed] = useState(false)

  useEffect(() => {
    setOverwriteArmed(false)
    setNote(null)
  }, [name])

  const save = useMutation({
    mutationFn: (overwrite: boolean) =>
      saveGraphView({
        name: name.trim(),
        layout: captureLayout(),
        filters,
        focusNode,
        overwrite,
      }),
    onSuccess: async (_data, overwrite) => {
      setNote(overwrite ? '已覆盖保存。' : '已保存。')
      setOverwriteArmed(false)
      await queryClient.invalidateQueries({ queryKey: ['graph-views'] })
    },
    onError: () => setNote('save-failed'),
  })

  const restore = (viewId: string) => {
    const view = (viewsQuery.data?.items ?? []).find((v) => v.id === viewId)
    if (view === undefined) return
    // 恢复语义：布局应用到存在节点（新节点默认位、失效节点跳过）
    applyGraphLayout(nodes, view.layout)
    onRestore({ layout: view.layout, filters: view.filters, focusNode: view.focusNode })
    setNote(`已恢复「${view.name}」。`)
  }

  const remove = useMutation({
    mutationFn: (id: string) => deleteGraphView(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['graph-views'] })
    },
  })

  const views = viewsQuery.data?.items ?? []
  const exists = views.some((v) => v.name === name.trim())

  return (
    <span data-lumi-graph-views="" className="inline-flex flex-wrap items-center gap-1.5">
      <Save aria-hidden className="size-3.5 text-[var(--lumi-text-tertiary)]" />
      <input
        aria-label="视图名称"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="视图名称"
        maxLength={50}
        className="w-28 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
      />
      <Button
        size="sm"
        variant="ghost"
        disabled={name.trim() === '' || save.isPending}
        onClick={() => (exists && !overwriteArmed ? setOverwriteArmed(true) : save.mutate(exists))}
      >
        {overwriteArmed ? '确认覆盖' : '保存当前'}
      </Button>
      {views.length > 0 && (
        <select
          aria-label="恢复命名视图"
          defaultValue=""
          onChange={(e) => {
            if (e.target.value !== '') restore(e.target.value)
            e.currentTarget.value = ''
          }}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
        >
          <option value="">恢复视图…</option>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      )}
      {views.some((v) => v.name === name.trim()) && (
        <Button
          size="sm"
          variant="ghost"
          disabled={remove.isPending || name.trim() === ''}
          onClick={() => {
            const target = views.find((v) => v.name === name.trim())
            if (target !== undefined) remove.mutate(target.id)
          }}
        >
          删除
        </Button>
      )}
      {note !== null && (
        <span role={note === 'save-failed' ? 'alert' : 'status'} className="text-[11px] text-[var(--lumi-text-tertiary)]">
          {note === 'save-failed' ? '保存失败。' : note}
        </span>
      )}
    </span>
  )
}
