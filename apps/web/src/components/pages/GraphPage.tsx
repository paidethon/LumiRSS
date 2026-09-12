/** GraphPage — phase2 G8：标签 / 关系图谱。
 *
 * App 已把本页接入 section='graph'（桌面 Timeline 列位 + 移动 section 区）。
 *
 * - 图谱是【只读派生视图】（BFF 每次从 item_tags / workspace_items /
 *   wikilinks 现算，无第二存储）；重建视图 = refetch。
 * - a11y 等价路径（图形永远不是唯一入口）：
 *   1) 顶部标签列表（非图形等价路径）：#名称 (数量) 可聚焦 chip；
 *   2) 画布下方始终有文字摘要行（共 N 节点 · M 边 · 截断提示）；
 *   3) 「显示为表格」语义 <table>（标签/类型/连接数），>500 节点默认
 *      表格，画布初始化失败（无 canvas 环境）也自动回退表格。
 * - cytoscape 动态 import（保持 lazy chunk）；布局用 grid（确定性、
 *   适合 prefers-reduced-motion：reduce 时 animate:false）。
 * - 节点颜色按 kind 读 CSS token 计算值（--lumi-category-*），不新增
 *   颜色；token 不可解析时（headless/测试）用同色系十六进制兜底。
 * - loading Skeleton / empty / error+重试 三态齐备。 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Loader2, MoreVertical, Pencil, RefreshCw, Trash2, Waypoints } from 'lucide-react'
import type { Core, ElementDefinition, StylesheetJson } from 'cytoscape'
import {
  useDeleteTagMutation,
  useGraph,
  useRenameTagMutation,
  useTags,
  useWorkspaces,
} from '../../api/queries'
import type { GraphNode, TagSummary } from '../../api/client'
import { resolveAndOpen } from '../../lib/open-item'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Menu } from '../ui/Menu'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 节点 > 500 时默认只列表格（画布对大图成本高、可读性差）。 */
const CANVAS_NODE_LIMIT = 500

/** 截断提示里的上限文案（与客户端请求的 max=2000 一致）。 */
const GRAPH_MAX_NODES = 2000

/** kind → 展示名（契约备注：library 子类经 label 体现，kind 仍是 library；
 * P0-10e：解析不到真实笔记的 wikilink 以 kind=unresolved 显式呈现）。 */
const KIND_LABELS: Record<string, string> = {
  tag: '标签',
  workspace: '工作区',
  wikilink: '笔记链接',
  rss: 'RSS',
  library: '库',
  unresolved: '未解析链接',
}

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** 可通过「打开」路由到真实内容的节点 kind（tag/workspace 是分组节点，
 * unresolved 没有目标——都不提供打开）。 */
const OPENABLE_NODE_KINDS = new Set(['rss', 'library'])

/** kind → CSS token（现有 --lumi-category-* 色板，不新增颜色）。 */
const KIND_COLOR_TOKENS: Record<string, [token: string, fallback: string]> = {
  tag: ['--lumi-category-purple', '#a855f7'],
  workspace: ['--lumi-category-blue', '#3b82f6'],
  wikilink: ['--lumi-category-green', '#22c55e'],
  rss: ['--lumi-category-orange', '#f97316'],
  library: ['--lumi-category-cyan', '#06b6d4'],
}

/** 读 token 计算值；不可解析（headless / 测试）→ 同色十六进制兜底。 */
function tokenColor(token: string, fallback: string): string {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim()
    return value !== '' ? value : fallback
  } catch {
    return fallback
  }
}

function kindColor(kind: string): string {
  const entry = KIND_COLOR_TOKENS[kind]
  if (entry === undefined) {
    return tokenColor('--lumi-text-tertiary', '#9ca3af')
  }
  return tokenColor(entry[0], entry[1])
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/** 画布：cytoscape 动态 import + grid 布局 + tap 选节点。失败回退表格。 */
function GraphCanvas({
  elements,
  colors,
  onFail,
  onSelect,
}: {
  elements: ElementDefinition[]
  colors: Record<string, string>
  onFail: () => void
  onSelect: (ref: string) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (container === null || elements.length === 0) return
    let destroyed = false
    let instance: Core | null = null

    void (async () => {
      try {
        // 动态 import：cytoscape 保持独立 lazy chunk（不进主包）。
        const cytoscape = (await import('cytoscape')).default
        const mount = containerRef.current
        if (destroyed || mount === null) return
        const nodeStyle: StylesheetJson = Object.entries(colors).map(([kind, color]) => ({
          selector: `node[kind = "${kind}"]`,
          style: { 'background-color': color },
        }))
        instance = cytoscape({
          container: mount,
          elements,
          style: [
            {
              selector: 'node',
              style: {
                label: 'data(label)',
                width: 14,
                height: 14,
                'font-size': 9,
                color: tokenColor('--lumi-text-secondary', '#6b7280'),
                'text-valign': 'bottom',
                'text-halign': 'center',
                'text-margin-y': 2,
              },
            },
            ...nodeStyle,
            {
              selector: 'edge',
              style: {
                width: 1,
                'line-color': tokenColor('--lumi-border', '#d1d5db'),
                'curve-style': 'haystack',
                'haystack-radius': 0.2,
                opacity: 0.6,
              },
            },
          ] satisfies StylesheetJson,
          layout: {
            name: 'grid',
            // 确定性布局；reduced-motion 用户关闭布局动画。
            animate: !prefersReducedMotion(),
            avoidOverlap: true,
            padding: 12,
            sort: (a, b) => a.id().localeCompare(b.id()),
          },
          minZoom: 0.2,
          maxZoom: 2,
        })
        instance.on('tap', 'node', (evt) => {
          const id = evt.target.id()
          if (typeof id === 'string') onSelect(id)
        })
      } catch {
        // 无 canvas / 初始化失败：诚实回退表格等价路径。
        if (!destroyed) onFail()
      }
    })()

    return () => {
      destroyed = true
      instance?.destroy()
    }
  }, [elements, colors, onFail, onSelect])

  return <div ref={containerRef} className="h-[420px] w-full" role="img" aria-label="关系图谱画布" />
}

export default function GraphPage() {
  const [scope, setScope] = useState('all')
  const [tablePreferred, setTablePreferred] = useState<boolean | null>(null)
  const [canvasFailed, setCanvasFailed] = useState(false)
  const [selectedRef, setSelectedRef] = useState<string | null>(null)

  const workspaces = useWorkspaces()
  const tags = useTags('')
  const graph = useGraph(scope)
  // P0-10：标签管理（重命名/删除）目标与模式（null = 关闭）。
  const [manageTag, setManageTag] = useState<TagSummary | null>(null)
  const [manageMode, setManageMode] = useState<'rename' | 'delete' | null>(null)

  const nodes = useMemo(() => graph.data?.nodes ?? [], [graph.data])
  const nodeRefs = useMemo(() => new Set(nodes.map((n) => n.ref)), [nodes])
  // 截断会丢节点：指向已丢弃节点的边不进画布（table 同一数据源）。
  const visibleEdges = useMemo(
    () => (graph.data?.edges ?? []).filter((e) => nodeRefs.has(e.src) && nodeRefs.has(e.dst)),
    [graph.data, nodeRefs],
  )

  const elements = useMemo<ElementDefinition[]>(
    () => [
      ...nodes.map((n) => ({
        data: { id: n.ref, label: n.label, kind: n.kind, degree: n.degree },
      })),
      ...visibleEdges.map((e) => ({ data: { source: e.src, target: e.dst, kind: e.kind } })),
    ],
    [nodes, visibleEdges],
  )

  const colors = useMemo(() => {
    const map: Record<string, string> = {}
    for (const node of nodes) {
      if (!(node.kind in map)) map[node.kind] = kindColor(node.kind)
    }
    return map
  }, [nodes])

  const overLimit = nodes.length > CANVAS_NODE_LIMIT
  const showTable = canvasFailed || (tablePreferred ?? overLimit)
  // 派生查找：scope/重建后 ref 消失时卡片自然不渲染，无需同步 effect。
  const selectedNode: GraphNode | null =
    selectedRef !== null ? (nodes.find((n) => n.ref === selectedRef) ?? null) : null

  // P0-02 wave 2：节点详情卡「打开」——resolve → 按 kind 路由
  // （Reader / 外链 / 剪藏 / 快照沙箱页 / Obsidian）；失败诚实透出。
  const [openState, setOpenState] = useState<{ busy: boolean; error: string | null }>({
    busy: false,
    error: null,
  })
  const openNode = async (ref: string) => {
    setOpenState({ busy: true, error: null })
    try {
      const resolved = await resolveAndOpen(ref)
      if (resolved === null) {
        setOpenState({ busy: false, error: '打开失败：内容解析请求未成功，请稍后重试。' })
        return
      }
      if (resolved.stale) {
        setOpenState({ busy: false, error: '内容已失效，无法打开。' })
        return
      }
      setOpenState({ busy: false, error: null })
    } catch (error) {
      setOpenState({
        busy: false,
        error: error instanceof Error ? error.message : '打开失败，请稍后重试。',
      })
    }
  }

  const scopeOptions = useMemo(
    () => [
      { value: 'all', label: '全部' },
      ...(workspaces.data?.items ?? []).map((ws) => ({
        value: `workspace:${ws.id}`,
        label: ws.name,
      })),
    ],
    [workspaces.data],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
      {/* 头部：标题 + 范围 + 重建视图 */}
      <div className="flex flex-wrap items-center gap-2 px-1">
        <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">标签 / 图谱</h2>
        <Select
          options={scopeOptions}
          value={scope}
          onChange={(e) => {
            setScope(e.target.value)
            setSelectedRef(null)
          }}
          aria-label="图谱范围"
          className="ml-auto"
        />
        <Button
          size="sm"
          variant="secondary"
          onClick={() => graph.refetch()}
          disabled={graph.isFetching}
        >
          <RefreshCw aria-hidden className={cx('size-3.5', graph.isFetching && 'animate-spin')} />
          重建视图
        </Button>
      </div>

      {/* 标签列表（非图形等价路径）：chip = #名称 (数量)，可聚焦 */}
      <section aria-labelledby="graph-tags-heading" className="mt-3 px-1">
        <h3 id="graph-tags-heading" className="text-xs font-semibold text-[var(--lumi-text-secondary)]">
          标签列表（非图形等价路径）
        </h3>
        {tags.isPending && (
          <div className="mt-1.5 flex gap-1.5" aria-label="标签加载中">
            <Skeleton className="h-6 w-20" />
            <Skeleton className="h-6 w-16" />
          </div>
        )}
        {tags.isError && (
          <p role="alert" className="mt-1.5 text-xs text-[var(--lumi-danger)]">
            {tags.error.message}
          </p>
        )}
        {tags.data !== undefined && tags.data.items.length === 0 && (
          <p className="mt-1.5 text-xs text-[var(--lumi-text-tertiary)]">暂无标签</p>
        )}
        {tags.data !== undefined && tags.data.items.length > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="标签列表">
            {tags.data.items.map((tag) => (
              <li key={tag.id} className="flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={() => {
                    const ref = `tag:${tag.name}`
                    if (nodeRefs.has(ref)) setSelectedRef(ref)
                  }}
                  aria-label={`标签 ${tag.name}，${tag.count} 条内容`}
                  className={cx(
                    'min-h-8 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-0.5 text-xs',
                    'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)]',
                    'hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  )}
                >
                  #{tag.name} ({tag.count})
                </button>
                {/* P0-10：标签管理（重命名 / 删除）——最小可发现面：图谱页
                    标签列表（唯一的真实标签清单视图）行内菜单。 */}
                <Menu
                  trigger={({ triggerProps }) => (
                    <IconButton
                      {...triggerProps}
                      icon={<MoreVertical aria-hidden className="size-3.5" />}
                      label={`管理标签 ${tag.name}`}
                      size="sm"
                    />
                  )}
                  items={[
                    {
                      key: 'rename',
                      content: (
                        <>
                          <Pencil aria-hidden className="mr-2 inline size-3.5" />
                          重命名
                        </>
                      ),
                    },
                    {
                      key: 'delete',
                      content: (
                        <>
                          <Trash2 aria-hidden className="mr-2 inline size-3.5" />
                          删除标签
                        </>
                      ),
                    },
                  ]}
                  onSelect={(key) => {
                    setManageTag(tag)
                    setManageMode(key === 'rename' ? 'rename' : 'delete')
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 图谱主体 */}
      <section aria-label="关系图谱" className="mt-3 flex min-h-0 flex-1 flex-col">
        {graph.isPending && (
          <div className="flex flex-col gap-2" aria-label="图谱加载中">
            <Skeleton className="h-[420px] w-full" />
          </div>
        )}

        {graph.isError && (
          <div role="alert" className="flex flex-col items-start gap-1.5 p-2 text-sm text-[var(--lumi-danger)]">
            <p className="flex items-center gap-1.5">
              <AlertCircle aria-hidden className="size-4 shrink-0" />
              {graph.error.message}
            </p>
            <Button size="sm" variant="secondary" onClick={() => graph.refetch()}>
              重试
            </Button>
          </div>
        )}

        {!graph.isPending && !graph.isError && nodes.length === 0 && (
          <EmptyState
            icon={<Waypoints aria-hidden className="size-10" />}
            title="还没有可绘制的关系"
            description="先在工作区/标签里创建关系——图谱是从标签绑定、工作区成员与笔记链接实时派生的只读视图。"
          />
        )}

        {!graph.isPending && !graph.isError && nodes.length > 0 && (
          <div className="flex min-h-0 flex-1 flex-col">
            {/* 文字摘要行（a11y 等价路径之一）：截断时如实区分真实总数
                与返回数（P0-10d——截断后的数量绝不冒充总数）。 */}
            <p role="status" className="px-1 text-xs text-[var(--lumi-text-secondary)]">
              {graph.data?.truncated === true ? (
                <>
                  真实总数 {graph.data.totalNodes} 节点 · 因过多仅返回{' '}
                  {graph.data.returnedNodes ?? nodes.length} 个 · {visibleEdges.length} 边
                  （按连接数截断，上限 {GRAPH_MAX_NODES}）
                </>
              ) : (
                <>共 {nodes.length} 节点 · {visibleEdges.length} 边</>
              )}
            </p>

            {/* 选中节点详情卡片（画布 tap / 标签 chip 均可触发） */}
            {selectedNode !== null && (
              <div
                className={cx(
                  'mt-2 rounded-[var(--lumi-radius-lg)] border px-3 py-2',
                  selectedNode.kind === 'unresolved'
                    ? 'border-dashed border-[var(--lumi-border)] bg-[var(--lumi-surface)] opacity-80'
                    : 'border-[var(--lumi-border)]',
                )}
                aria-live="polite"
              >
                <div className="flex items-center gap-2">
                  <p className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                    {selectedNode.label}
                  </p>
                  {OPENABLE_NODE_KINDS.has(selectedNode.kind) && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={openState.busy}
                      onClick={() => void openNode(selectedNode.ref)}
                    >
                      打开
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setSelectedRef(null)}>
                    关闭
                  </Button>
                </div>
                <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
                  类型：{kindLabel(selectedNode.kind)} · 连接数：{selectedNode.degree}
                </p>
                {selectedNode.kind === 'unresolved' && (
                  <p className="mt-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                    这个笔记链接在库内没有解析到真实笔记（目标不存在或尚未扫描）。
                  </p>
                )}
                <p className="mt-0.5 text-[11px] break-all text-[var(--lumi-text-tertiary)]">
                  {selectedNode.ref}
                </p>
                {openState.error !== null && (
                  <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
                    {openState.error}
                  </p>
                )}
              </div>
            )}

            {/* 视图切换（canvas 不可用时隐藏，回退说明替代） */}
            {!canvasFailed && (
              <div className="mt-2 flex items-center gap-2 px-1">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-pressed={showTable}
                  onClick={() => setTablePreferred(!showTable)}
                >
                  {showTable ? '显示为图形' : '显示为表格'}
                </Button>
                {overLimit && (
                  <span className="text-xs text-[var(--lumi-text-tertiary)]">
                    节点过多（超过 {CANVAS_NODE_LIMIT}），默认以表格显示。
                  </span>
                )}
              </div>
            )}
            {canvasFailed && (
              <p className="mt-2 px-1 text-xs text-[var(--lumi-text-tertiary)]" role="status">
                图形画布在当前环境不可用，已回退为表格视图。
              </p>
            )}

            {showTable ? (
              <table className="mt-2 w-full border-collapse text-sm">
                <caption className="sr-only">图谱节点列表（标签 / 类型 / 连接数）</caption>
                <thead>
                  <tr className="border-b border-[var(--lumi-border)] text-left text-xs text-[var(--lumi-text-tertiary)]">
                    <th scope="col" className="py-1.5 pr-2 font-medium">标签</th>
                    <th scope="col" className="py-1.5 pr-2 font-medium">类型</th>
                    <th scope="col" className="py-1.5 font-medium">连接数</th>
                  </tr>
                </thead>
                <tbody>
                  {nodes.map((node) => (
                    <tr
                      key={node.ref}
                      className="border-b border-[var(--lumi-separator)] text-[var(--lumi-text-secondary)]"
                    >
                      <td className="py-1.5 pr-2 text-[var(--lumi-text-primary)]">{node.label}</td>
                      <td className="py-1.5 pr-2">{kindLabel(node.kind)}</td>
                      <td className="py-1.5">{node.degree}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="mt-2 overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
                <GraphCanvas
                  elements={elements}
                  colors={colors}
                  onFail={() => setCanvasFailed(true)}
                  onSelect={setSelectedRef}
                />
              </div>
            )}
          </div>
        )}
      </section>

      {/* P0-10：标签管理对话框（条件挂载）。 */}
      {manageTag !== null && manageMode === 'rename' && (
        <TagRenameDialog
          tag={manageTag}
          onClose={() => {
            setManageTag(null)
            setManageMode(null)
          }}
        />
      )}
      {manageTag !== null && manageMode === 'delete' && (
        <TagDeleteDialog
          tag={manageTag}
          onClose={() => {
            setManageTag(null)
            setManageMode(null)
          }}
        />
      )}
    </div>
  )
}

/** P0-10：重命名标签（条件挂载；RenameCategoryDialog 模式：预填现名 +
 * 空名/未变更禁用提交 + 服务端错误内联）。 */
function TagRenameDialog({ tag, onClose }: { tag: TagSummary; onClose: () => void }) {
  const [name, setName] = useState(tag.name)
  const rename = useRenameTagMutation()
  const trimmed = name.trim()
  const canSubmit = trimmed !== '' && trimmed !== tag.name && !rename.isPending

  return (
    <Dialog
      open
      onClose={onClose}
      title="重命名标签"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={rename.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            onClick={() => {
              if (!canSubmit) return
              rename.mutate({ tagId: tag.id, name: trimmed }, { onSuccess: onClose })
            }}
          >
            {rename.isPending ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSubmit) return
          rename.mutate({ tagId: tag.id, name: trimmed }, { onSuccess: onClose })
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">标签名</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={64}
            autoFocus
            aria-label="标签名"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
      </form>
      {rename.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {rename.error instanceof Error ? rename.error.message : '重命名失败，请稍后重试。'}
        </p>
      )}
    </Dialog>
  )
}

/** P0-10：删除标签（破坏性：解除全部条目绑定；双重确认，不做乐观更新）。 */
function TagDeleteDialog({ tag, onClose }: { tag: TagSummary; onClose: () => void }) {
  const [stage, setStage] = useState<'confirm' | 'final'>('confirm')
  const remove = useDeleteTagMutation()
  const busy = remove.isPending

  return (
    <Dialog
      open
      onClose={() => {
        if (!busy) onClose()
      }}
      title={stage === 'confirm' ? '删除标签' : '再次确认'}
      footer={
        stage === 'confirm' ? (
          <>
            <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              保留标签
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStage('final')} disabled={busy}>
              删除标签
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" size="sm" onClick={() => setStage('confirm')} disabled={busy}>
              返回
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={busy}
              onClick={() => remove.mutate(tag.id, { onSuccess: onClose })}
            >
              {busy ? (
                <>
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                  删除中…
                </>
              ) : (
                <>
                  <Trash2 aria-hidden className="size-4" />
                  确认删除
                </>
              )}
            </Button>
          </>
        )
      }
    >
      <p className="text-sm text-[var(--lumi-text-secondary)]">
        将删除标签「#{tag.name}」并解除 {tag.count} 条内容上的绑定。内容本身不受影响。
      </p>
      {stage === 'final' && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
        >
          <Trash2 aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block font-medium">确定要删除这个标签吗？</span>
            <span className="mt-0.5 block text-xs opacity-80">此操作无法撤销。</span>
          </span>
        </div>
      )}
      {remove.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {remove.error instanceof Error ? remove.error.message : '删除失败，请稍后重试。'}
        </p>
      )}
    </Dialog>
  )
}
