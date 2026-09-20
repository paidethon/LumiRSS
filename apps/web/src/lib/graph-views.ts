/** graph-views — F076 图谱命名视图（纯逻辑 + 客户端函数）。
 *
 * 布局应用语义（可单测）：
 * - 存在节点 → 应用保存的位置；
 * - 新增节点（布局中无）→ 默认位（0,0），不崩；
 * - 失效节点（节点已不在图中）→ 跳过，不影响其余应用；
 * - 恢复 filters 与 focus 由调用方执行（本模块只做布局）。 */


export interface GraphViewPayload {
  id: string
  name: string
  layout: Record<string, { x: number; y: number }>
  filters: Record<string, unknown>
  focusNode: string | null
  createdAt: string
  updatedAt: string
}

export interface GraphNodeLike {
  ref: string
}

export interface LayoutApplyResult {
  positions: Map<string, { x: number; y: number }>
  applied: number
  defaulted: number
  skipped: number
}

/** 应用保存布局到当前节点集合（存在→位置；新增→默认位；失效→跳过）。 */
export function applyGraphLayout(
  nodes: GraphNodeLike[],
  layout: Record<string, { x: number; y: number }>,
  defaultPosition: { x: number; y: number } = { x: 0, y: 0 },
): LayoutApplyResult {
  const positions = new Map<string, { x: number; y: number }>()
  let applied = 0
  let defaulted = 0
  let skipped = 0
  const layoutRefs = new Set(Object.keys(layout))
  for (const node of nodes) {
    const saved = layout[node.ref]
    if (saved !== undefined) {
      positions.set(node.ref, { x: saved.x, y: saved.y })
      applied += 1
      layoutRefs.delete(node.ref)
    } else {
      positions.set(node.ref, { ...defaultPosition })
      defaulted += 1
    }
  }
  skipped = layoutRefs.size
  return { positions, applied, defaulted, skipped }
}
