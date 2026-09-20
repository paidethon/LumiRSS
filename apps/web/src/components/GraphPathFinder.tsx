/** GraphPathFinder — F077 关系路径查找（GraphPage 工具栏）。
 *
 * 两节点选择（datalist 搜索）→ BFS 路径（≤5 条）→ 节点链 chips
 * （边类型标注）→ 点击节点打开内容。 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { findGraphPath } from '../api/client'
import { resolveAndOpen } from '../lib/open-item'
import type { GraphNodeLike } from '../lib/graph-views'
import { Button } from './ui/Button'

export function GraphPathFinder({ nodes }: { nodes: GraphNodeLike[] & { label?: string }[] }) {
  const [open, setOpen] = useState(false)
  const [src, setSrc] = useState('')
  const [dst, setDst] = useState('')
  const [maxDepth, setMaxDepth] = useState(4)
  const path = useMutation({
    mutationFn: () => findGraphPath({ srcRef: src.trim(), dstRef: dst.trim(), maxDepth }),
  })

  const nodeLabels = new Map<string, string>()
  for (const node of nodes as unknown as { ref: string; label?: string }[]) {
    nodeLabels.set(node.ref, node.label ?? node.ref)
  }
  const openNode = async (ref: string) => {
    try {
      await resolveAndOpen(ref)
    } catch {
      /* 打开失败静默（节点可能为 tag/ws 派生节点） */
    }
  }

  return (
    <span data-lumi-graph-path="" className="inline-flex flex-wrap items-center gap-1.5">
      <Button size="sm" variant="secondary" onClick={() => setOpen((v) => !v)}>
        查找路径
      </Button>
      {open && (
        <span className="flex flex-wrap items-center gap-1.5">
          <input
            aria-label="起点节点"
            list="graph-path-nodes"
            value={src}
            onChange={(e) => setSrc(e.target.value)}
            placeholder="起点"
            className="w-40 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <input
            aria-label="终点节点"
            list="graph-path-nodes"
            value={dst}
            onChange={(e) => setDst(e.target.value)}
            placeholder="终点"
            className="w-40 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <datalist id="graph-path-nodes">
            {Array.from(nodeLabels.entries()).slice(0, 200).map(([ref, label]) => (
              <option key={ref} value={ref}>
                {label}
              </option>
            ))}
          </datalist>
          <select
            aria-label="最大深度"
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value))}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
          >
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                深度 {n}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="primary"
            disabled={src.trim() === '' || dst.trim() === '' || path.isPending}
            onClick={() => path.mutate()}
          >
            {path.isPending ? '查找中…' : '查找'}
          </Button>
        </span>
      )}
      {open && path.data !== null && path.data !== undefined && (
        <span className="flex flex-col gap-1.5" data-lumi-graph-path-result="">
          {!path.data.reachable && (
            <span role="status" className="text-xs text-[var(--lumi-text-tertiary)]">
              不可达：两节点间在当前图内没有路径。
            </span>
          )}
          {path.data.paths.map((p, i) => (
            <span
              key={i}
              className="flex flex-wrap items-center gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-1.5"
            >
              {p.nodes.map((node, j) => (
                <span key={node.ref + j} className="inline-flex items-center gap-1">
                  {j > 0 && (
                    <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
                      — {p.edgeKinds[j - 1] ?? ''} →
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void openNode(node.ref)}
                    title={node.label}
                    className="max-w-40 truncate rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                  >
                    {node.label}
                  </button>
                </span>
              ))}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}
