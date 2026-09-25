/** WorkspaceOutlinePanel — N113 分节大纲 + N114 汇编预览 + N120 清理预演。
 *
 * 大纲（N113）：显式分节列表（sort_index 序），节内成员 position 序；
 * 同一条目可出现在多个分节（引用而非复制，重复出现原样显示 + 「重复」
 * 角标）；引用已不在工作区 → 诚实 unresolved 标记（绝不静默隐藏）。
 * 分节：新建 / 重命名 / 删除 / 上下移（PUT order 全量重排，持久化）。
 * 汇编预览（N114）：按大纲汇编草稿（纯预览不落库）——每节标题 + 条目
 * （标题/摘录≤200/引文/笔记），缺失引用诚实排除并计数；「下载 Markdown」
 * 出口（研究包 ZIP 导出不带分节过滤，故按规格走 Markdown 下载）。
 * 分享包（N116）：「导出分享包」——自包含静态 HTML（无脚本/凭据/本地
 * 路径；私人笔记绝不进包，includeNotes 固定 false）。
 * 冲突对照（N156）：「资料冲突对照」——选 2–5 份材料做纯词法句级比对
 * （零模型调用；基于文本比对，非语义裁决）。
 * 清理预演（N120）：只读报告（逐项带原因）→ 勾选可执行类目 → 应用
 * （服务端快照先行）→ 撤销（恢复被移除的行）。绝不触碰 FreshRSS 数据；
 * library 引用受保护（服务端强制；UI 只提供可执行类目的勾选）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Eraser,
  FileText,
  Loader2,
  Pencil,
  Plus,
  Share2,
  Trash2,
  Undo2,
  Scale,
} from 'lucide-react'
import {
  applyWorkspaceCleanup,
  CLEANUP_CATEGORY_LABELS,
  compileWorkspace,
  compileWorkspaceMarkdown,
  exportSharePackage,
  qaConflicts,
  createWorkspaceSection,
  deleteWorkspaceSection,
  getWorkspaceCleanupPreview,
  listWorkspaceSections,
  removeWorkspaceSectionItem,
  renameWorkspaceSection,
  reorderWorkspaceSectionItems,
  reorderWorkspaceSections,
  undoWorkspaceCleanup,
  type WorkspaceSectionView,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { IconButton } from './ui/IconButton'
import { Skeleton } from './ui/Skeleton'

function useInvalidateSections(workspaceId: string) {
  const queryClient = useQueryClient()
  return async () => {
    await queryClient.invalidateQueries({
      queryKey: ['workspace-sections', workspaceId],
    })
    await queryClient.invalidateQueries({
      queryKey: ['workspace-cleanup-preview', workspaceId],
    })
    await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }
}

/** N114：汇编草稿视图（useQuery 获取；下载走 markdown 端点）。 */
function CompileDraftView({
  workspaceId,
  onDone,
}: {
  workspaceId: string
  onDone: () => void
}) {
  const draft = useQuery({
    queryKey: ['workspace-compile', workspaceId],
    queryFn: () => compileWorkspace(workspaceId),
  })
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const download = useMutation({
    mutationFn: () => compileWorkspaceMarkdown(workspaceId),
    onSuccess: (text) => {
      const blob = new Blob([text], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `compile-${workspaceId}.md`
      a.click()
      URL.revokeObjectURL(url)
    },
    onError: (err) => {
      setDownloadError(err instanceof Error ? err.message : '下载失败，请稍后重试。')
    },
  })
  // N116：导出只读分享包（自包含 HTML；私人笔记绝不进包）。
  const share = useMutation({
    mutationFn: () => exportSharePackage(workspaceId),
    onError: (err) => {
      setDownloadError(err instanceof Error ? err.message : '分享包导出失败，请稍后重试。')
    },
  })
  // N156：资料冲突对照入口（可选材料 = 本草稿条目）。
  const [conflictsOpen, setConflictsOpen] = useState(false)

  return (
    <div
      data-testid="compile-draft"
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
          <FileText aria-hidden className="size-4" />
          汇编草稿
        </h3>
        <span className="text-[11px] text-[var(--lumi-text-tertiary)]">纯预览 · 不落库</span>
        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="secondary"
            size="sm"
            disabled={draft.data === undefined || download.isPending}
            onClick={() => download.mutate()}
          >
            {download.isPending ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <Download aria-hidden className="size-3.5" />
            )}
            下载 Markdown
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={draft.data === undefined || share.isPending}
            onClick={() => share.mutate()}
          >
            {share.isPending ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <Share2 aria-hidden className="size-3.5" />
            )}
            导出分享包
          </Button>
          <Button variant="ghost" size="sm" onClick={onDone}>
            关闭
          </Button>
        </div>
      </div>
      {downloadError !== null && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {downloadError}
        </p>
      )}
      {draft.data !== undefined && (
        <div className="mt-2">
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={conflictsOpen}
            onClick={() => setConflictsOpen((v) => !v)}
          >
            <Scale aria-hidden className="size-3.5" />
            资料冲突对照
          </Button>
        </div>
      )}
      {conflictsOpen && draft.data !== undefined && (
        <QaConflictsDialog
          materials={draft.data.sections.flatMap((section) =>
            section.items.map((item) => ({
              ref: item.itemRef.startsWith('rss:')
                ? item.itemRef.slice('rss:'.length)
                : item.itemRef,
              title: item.title,
            })),
          )}
          onClose={() => setConflictsOpen(false)}
        />
      )}
      {draft.isPending && <Skeleton className="mt-2 h-32 w-full" />}
      {draft.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          汇编失败：{draft.error instanceof Error ? draft.error.message : '请稍后重试。'}
        </p>
      )}
      {draft.data !== undefined && (
        <div className="mt-2 flex flex-col gap-3" data-testid="compile-draft-body">
          <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
            收录 {draft.data.includedCount} 条 · 排除 {draft.data.excludedMissing} 条
            {draft.data.excludedMissing > 0 ? '（缺失或未授权，诚实排除）' : ''}
          </p>
          {draft.data.sections.map((section, index) => (
            <section
              key={section.sectionId ?? `flat-${index}`}
              aria-label={`汇编节 ${section.title}`}
            >
              <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">
                {section.title}
              </h4>
              {section.items.length === 0 ? (
                <p className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">
                  （本节暂无可汇编条目）
                </p>
              ) : (
                <ul className="mt-1 flex flex-col gap-1.5">
                  {section.items.map((item) => (
                    <li
                      key={`${section.sectionId ?? 'flat'}-${item.itemRef}`}
                      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-xs"
                    >
                      <p className="font-medium text-[var(--lumi-text-primary)]">{item.title}</p>
                      {item.excerpt !== '' && (
                        <p className="mt-0.5 text-[var(--lumi-text-secondary)]">{item.excerpt}</p>
                      )}
                      <p className="mt-0.5 truncate text-[var(--lumi-text-tertiary)]">
                        引文：<code className="text-[10px]">{item.citation}</code>
                      </p>
                      {item.note != null && item.note !== '' && (
                        <p className="mt-0.5 text-[var(--lumi-text-secondary)]">笔记：{item.note}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

/** N120：清理预演面板（只读报告 → 勾选应用 → 撤销）。 */
function CleanupPanel({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const preview = useQuery({
    queryKey: ['workspace-cleanup-preview', workspaceId],
    queryFn: ({ signal }) => getWorkspaceCleanupPreview(workspaceId, signal),
  })
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [applyError, setApplyError] = useState<string | null>(null)
  const [applied, setApplied] = useState<{ logId: string; removed: Record<string, number> } | null>(
    null,
  )
  const invalidate = useInvalidateSections(workspaceId)

  const apply = useMutation({
    mutationFn: () => applyWorkspaceCleanup(workspaceId, [...selected]),
    onSuccess: async (result) => {
      setApplied({ logId: result.logId, removed: result.removed })
      setSelected(new Set())
      setApplyError(null)
      await invalidate()
    },
    onError: (err) => {
      setApplyError(err instanceof Error ? err.message : '清理失败，请稍后重试。')
    },
  })
  const undo = useMutation({
    mutationFn: () => undoWorkspaceCleanup(workspaceId, applied?.logId ?? null),
    onSuccess: async () => {
      setApplied(null)
      await invalidate()
    },
  })

  const data = preview.data
  const hasAny =
    data !== undefined && data.categories.some((c) => c.items.length > 0)

  return (
    <div
      data-testid="workspace-cleanup-panel"
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
          <Eraser aria-hidden className="size-4" />
          清理预演
        </h3>
        <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
          只读报告 · 应用前自动快照（可撤销）· 绝不触碰 FreshRSS 数据
        </span>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose}>
          关闭
        </Button>
      </div>
      {preview.isPending && <Skeleton className="mt-2 h-24 w-full" />}
      {preview.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          预演加载失败：{preview.error instanceof Error ? preview.error.message : '请稍后重试。'}
        </p>
      )}
      {data !== undefined && (
        <div className="mt-2 flex flex-col gap-2">
          {!hasAny && (
            <p className="text-xs text-[var(--lumi-text-secondary)]" data-testid="cleanup-empty">
              没有发现可清理的项目。
            </p>
          )}
          {data.categories
            .filter((c) => c.items.length > 0)
            .map((category) => {
              const actionable = data.actionable.includes(category.category)
              const label = CLEANUP_CATEGORY_LABELS[category.category] ?? category.category
              return (
                <fieldset key={category.category} className="flex flex-col gap-1">
                  <legend className="flex items-center gap-2 text-xs text-[var(--lumi-text-primary)]">
                    {actionable && (
                      <input
                        type="checkbox"
                        aria-label={`选择清理类目：${label}`}
                        checked={selected.has(category.category)}
                        onChange={() =>
                          setSelected((prev) => {
                            const next = new Set(prev)
                            if (next.has(category.category)) next.delete(category.category)
                            else next.add(category.category)
                            return next
                          })
                        }
                      />
                    )}
                    {label}
                    <span className="rounded-full bg-[var(--lumi-surface-selected)] px-1.5 text-[10px]">
                      {category.items.length}
                    </span>
                    {!actionable && (
                      <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
                        仅报告（不可清理）
                      </span>
                    )}
                  </legend>
                  <ul className="ml-5 flex flex-col gap-0.5">
                    {category.items.slice(0, 20).map((item, index) => (
                      <li key={index} className="text-[11px] text-[var(--lumi-text-secondary)]">
                        {String(item.itemRef ?? item.name ?? '')}
                        {typeof item.reason === 'string' ? ` — ${item.reason}` : ''}
                      </li>
                    ))}
                    {category.items.length > 20 && (
                      <li className="text-[11px] text-[var(--lumi-text-tertiary)]">
                        …共 {category.items.length} 项
                      </li>
                    )}
                  </ul>
                </fieldset>
              )
            })}
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={apply.isPending}
                onClick={() => apply.mutate()}
              >
                {apply.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Eraser aria-hidden className="size-4" />
                )}
                应用选中的清理（{selected.size} 类）
              </Button>
              <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
                只删 Lumi 元数据行；库对象受保护
              </span>
            </div>
          )}
          {applied !== null && (
            <div
              role="status"
              data-testid="cleanup-applied"
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-selected)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
            >
              <span>
                已清理：条目 {applied.removed.unresolvedRefs ?? 0} · 空组{' '}
                {applied.removed.emptyGroups ?? 0} · 分节引用{' '}
                {applied.removed.orphanSectionRefs ?? 0}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                disabled={undo.isPending}
                onClick={() => undo.mutate()}
              >
                {undo.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Undo2 aria-hidden className="size-4" />
                )}
                撤销
              </Button>
            </div>
          )}
          {(applyError !== null || undo.isError) && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {applyError ?? (undo.error instanceof Error ? undo.error.message : '撤销失败。')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** 单个分节卡片（节内条目列表 + 行内动作）。 */
function SectionCard({
  workspaceId,
  section,
  memberTitles,
  onRename,
  onDelete,
}: {
  workspaceId: string
  section: WorkspaceSectionView
  memberTitles: Map<string, string>
  onRename: (section: WorkspaceSectionView) => void
  onDelete: (section: WorkspaceSectionView) => void
}) {
  const invalidate = useInvalidateSections(workspaceId)
  const remove = useMutation({
    mutationFn: (itemRef: string) =>
      removeWorkspaceSectionItem(workspaceId, section.id, itemRef),
    onSuccess: invalidate,
  })
  const reorderItems = useMutation({
    mutationFn: (itemRefs: string[]) =>
      reorderWorkspaceSectionItems(workspaceId, section.id, itemRefs),
    onSuccess: invalidate,
  })
  const [collapsed, setCollapsed] = useState(false)

  const moveItem = (index: number, delta: -1 | 1) => {
    const refs = section.items.map((i) => i.itemRef)
    const target = index + delta
    if (target < 0 || target >= refs.length) return
    const next = [...refs]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    reorderItems.mutate(next)
  }

  // 同一条目在本节重复出现（引用可重复入节；跨节重复在整表层面呈现）
  const counts = new Map<string, number>()
  for (const item of section.items) counts.set(item.itemRef, (counts.get(item.itemRef) ?? 0) + 1)

  return (
    <section
      aria-label={`分节 ${section.title}`}
      data-testid={`workspace-section-${section.id}`}
      className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2"
    >
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-expanded={!collapsed}
          aria-label={`折叠分节 ${section.title}`}
          onClick={() => setCollapsed((v) => !v)}
          className="flex min-h-8 items-center px-0.5 text-[var(--lumi-text-secondary)]"
        >
          {collapsed ? (
            <ChevronRight aria-hidden className="size-3.5" />
          ) : (
            <ChevronDown aria-hidden className="size-3.5" />
          )}
        </button>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-[var(--lumi-text-primary)]">
          {section.title}
        </span>
        <span className="rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]">
          {section.items.length}
        </span>
        <IconButton
          icon={<Pencil aria-hidden className="size-3.5" />}
          label={`重命名分节 ${section.title}`}
          size="sm"
          onClick={() => onRename(section)}
        />
        <IconButton
          icon={<Trash2 aria-hidden className="size-3.5" />}
          label={`删除分节 ${section.title}`}
          size="sm"
          touch
          disabled={onDelete === undefined}
          onClick={() => onDelete(section)}
        />
      </div>
      {!collapsed && (
        <ul className="mt-1.5 flex flex-col gap-1">
          {section.items.map((item, index) => (
            <li
              key={`${item.itemRef}-${index}`}
              className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1 text-xs"
              data-section-item={item.itemRef}
            >
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                {memberTitles.get(item.itemRef) ?? item.itemRef.slice(0, 16)}
              </span>
              {(counts.get(item.itemRef) ?? 0) > 1 && (
                <span className="flex shrink-0 items-center gap-1 text-[10px] text-[var(--lumi-text-tertiary)]">
                  <Copy aria-hidden className="size-3" />
                  重复引用
                </span>
              )}
              {item.unresolved && (
                <span
                  className="flex shrink-0 items-center gap-1 text-[10px] text-[var(--lumi-danger)]"
                  data-testid="section-item-unresolved"
                >
                  <AlertTriangle aria-hidden className="size-3" />
                  已不在工作区
                </span>
              )}
              <IconButton
                icon={<ArrowUp aria-hidden className="size-3.5" />}
                label={`上移条目（${section.title}）`}
                size="sm"
                disabled={index === 0 || reorderItems.isPending}
                onClick={() => moveItem(index, -1)}
              />
              <IconButton
                icon={<ArrowDown aria-hidden className="size-3.5" />}
                label={`下移条目（${section.title}）`}
                size="sm"
                disabled={index === section.items.length - 1 || reorderItems.isPending}
                onClick={() => moveItem(index, 1)}
              />
              <IconButton
                icon={<Trash2 aria-hidden className="size-3.5" />}
                label={`移出分节 ${section.title}`}
                size="sm"
                touch
                disabled={remove.isPending}
                onClick={() => remove.mutate(item.itemRef)}
              />
            </li>
          ))}
          {section.items.length === 0 && (
            <li className="text-[11px] text-[var(--lumi-text-tertiary)]">
              本节还没有条目（在「列表」视图的条目菜单里「移动到分节」）。
            </li>
          )}
        </ul>
      )}
    </section>
  )
}

/** 大纲面板（N113 主入口；含 N114 汇编预览与 N120 清理预演）。 */
export function WorkspaceOutlinePanel({
  workspaceId,
  memberTitles,
}: {
  workspaceId: string
  /** 工作区成员 ref → 标题（展示用；缺失时截断 ref）。 */
  memberTitles: Map<string, string>
}) {
  const sections = useQuery({
    queryKey: ['workspace-sections', workspaceId],
    queryFn: ({ signal }) => listWorkspaceSections(workspaceId, signal),
  })
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [compileOpen, setCompileOpen] = useState(false)
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState<WorkspaceSectionView | null>(null)
  const [renameText, setRenameText] = useState('')
  const invalidate = useInvalidateSections(workspaceId)
  const create = useMutation({
    mutationFn: () => createWorkspaceSection(workspaceId, newTitle.trim()),
    onSuccess: async () => {
      setNewTitle('')
      setCreating(false)
      await invalidate()
    },
  })
  const rename = useMutation({
    mutationFn: () =>
      renameWorkspaceSection(workspaceId, renameTarget?.id ?? '', renameText.trim()),
    onSuccess: async () => {
      setRenameTarget(null)
      await invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: (sectionId: string) => deleteWorkspaceSection(workspaceId, sectionId),
    onSuccess: invalidate,
  })
  const reorder = useMutation({
    mutationFn: (sectionIds: string[]) => reorderWorkspaceSections(workspaceId, sectionIds),
    onSuccess: invalidate,
  })
  const [actionError, setActionError] = useState<string | null>(null)
  const onError = (error: unknown, fallback: string) => {
    setActionError(error instanceof Error ? error.message : fallback)
  }

  const items = sections.data?.items ?? []
  const moveSection = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= items.length) return
    const ids = items.map((s) => s.id)
    const next = [...ids]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    reorder.mutate(next)
  }

  return (
    <div className="mt-3 flex flex-col gap-3" data-testid="workspace-outline">
      <div className="flex flex-wrap items-center gap-2">
        {creating ? (
          <span className="flex items-center gap-1.5">
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="分节标题"
              aria-label="新分节标题"
              maxLength={100}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)]"
            />
            <Button
              variant="primary"
              size="sm"
              disabled={newTitle.trim() === '' || create.isPending}
              onClick={() => create.mutate()}
            >
              创建
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>
              取消
            </Button>
          </span>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-4" />
            新建分节
          </Button>
        )}
        <Button
          variant="secondary"
          size="sm"
          aria-pressed={compileOpen}
          onClick={() => setCompileOpen((v) => !v)}
        >
          <FileText aria-hidden className="size-4" />
          汇编预览
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-pressed={cleanupOpen}
          onClick={() => setCleanupOpen((v) => !v)}
        >
          <Eraser aria-hidden className="size-4" />
          清理预演
        </Button>
        {items.length > 0 && (
          <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
            在「列表」视图的条目菜单里可把条目移入分节
          </span>
        )}
      </div>
      {(create.isError || rename.isError || actionError !== null) && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {actionError ??
            (create.error instanceof Error
              ? create.error.message
              : rename.error instanceof Error
                ? rename.error.message
                : '操作失败。')}
        </p>
      )}
      {compileOpen && (
        <CompileDraftView workspaceId={workspaceId} onDone={() => setCompileOpen(false)} />
      )}
      {cleanupOpen && (
        <CleanupPanel workspaceId={workspaceId} onClose={() => setCleanupOpen(false)} />
      )}
      {sections.isPending ? (
        <Skeleton className="h-24 w-full" aria-label="大纲加载中" />
      ) : sections.isError ? (
        <div role="alert" className="text-xs text-[var(--lumi-danger)]">
          大纲加载失败：{sections.error instanceof Error ? sections.error.message : '请稍后重试。'}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<FileText aria-hidden className="size-8" />}
          title="还没有分节大纲"
          description="新建分节后，可把列表条目移入不同分节；汇编预览会按大纲生成草稿。"
        />
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((section, index) => (
            <div key={section.id}>
              <div className="mb-1 flex items-center gap-1">
                <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
                  第 {index + 1} 节
                </span>
                <span className="ml-auto flex items-center gap-1">
                  <IconButton
                    icon={<ArrowUp aria-hidden className="size-3.5" />}
                    label={`上移分节 ${section.title}`}
                    size="sm"
                    disabled={index === 0 || reorder.isPending}
                    onClick={() => moveSection(index, -1)}
                  />
                  <IconButton
                    icon={<ArrowDown aria-hidden className="size-3.5" />}
                    label={`下移分节 ${section.title}`}
                    size="sm"
                    disabled={index === items.length - 1 || reorder.isPending}
                    onClick={() => moveSection(index, 1)}
                  />
                </span>
              </div>
              <SectionCard
                workspaceId={workspaceId}
                section={section}
                memberTitles={memberTitles}
                onRename={(target) => {
                  setRenameTarget(target)
                  setRenameText(target.title)
                }}
                onDelete={(target) => {
                  setActionError(null)
                  remove.mutate(target.id, {
                    onError: (error) => onError(error, '删除分节失败。'),
                  })
                }}
              />
              {renameTarget?.id === section.id && (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <input
                    type="text"
                    value={renameText}
                    onChange={(e) => setRenameText(e.target.value)}
                    aria-label="分节新标题"
                    maxLength={100}
                    className="min-h-8 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)]"
                  />
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={renameText.trim() === '' || rename.isPending}
                    onClick={() => rename.mutate()}
                  >
                    保存
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setRenameTarget(null)}>
                    取消
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** N156：资料冲突对照 Dialog —— 纯词法比对（零模型调用）。
 * 选择 2–5 份材料 → POST /qa/conflicts → 冲突句并列展示
 * （数字/日期/其他）。诚实口径：基于文本比对，非语义裁决——差异
 * 不必然是错误，判断留给读者。 */
function QaConflictsDialog({
  materials,
  onClose,
}: {
  materials: { ref: string; title: string }[]
  onClose: () => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<Awaited<ReturnType<typeof qaConflicts>> | null>(null)
  const run = useMutation({
    mutationFn: () => qaConflicts([...selected]),
    onSuccess: setResult,
  })
  const toggle = (ref: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else if (prev.size < 5) next.add(ref)
      return next
    })
  }

  return (
    <Dialog open onClose={onClose} title="资料冲突对照" panelClassName="max-w-xl">
      <div className="flex flex-col gap-2" data-testid="qa-conflicts">
        <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
          纯文本比对（零模型调用）：找出高度相似但数字/日期不同的句子对。
          基于文本比对，非语义裁决——差异不必然是错误。
        </p>
        {materials.length < 2 ? (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            本草稿的可对照材料不足 2 条，无法对照。
          </p>
        ) : (
          <fieldset className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs">
            <legend className="px-1 text-[var(--lumi-text-secondary)]">
              选择材料（2–5 份）
            </legend>
            {materials.map((material) => (
              <label key={material.ref} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected.has(material.ref)}
                  onChange={() => toggle(material.ref)}
                  aria-label={`选择材料：${material.title}`}
                />
                <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                  {material.title}
                </span>
              </label>
            ))}
          </fieldset>
        )}
        <div>
          <Button
            variant="primary"
            size="sm"
            disabled={selected.size < 2 || run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending ? '比对中…' : `比对所选（${selected.size}）`}
          </Button>
        </div>
        {run.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {run.error instanceof Error ? run.error.message : '比对失败，请稍后重试。'}
          </p>
        )}
        {result !== null && (
          <div className="flex flex-col gap-1.5" data-conflicts-result="">
            {result.conflicts.length === 0 && (
              <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
                未检出高重叠的句级差异。
              </p>
            )}
            {result.conflicts.map((conflict, index) => (
              <div
                key={`${conflict.aRef}-${conflict.bRef}-${index}`}
                data-conflict-kind={conflict.diffKind}
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs"
              >
                <p className="flex items-center gap-1.5">
                  <span className="rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                    {conflict.diffKind === 'number'
                      ? '数字差异'
                      : conflict.diffKind === 'date'
                        ? '日期差异'
                        : '其他差异'}
                  </span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    重叠 {Math.round(conflict.overlap * 100)}%
                  </span>
                </p>
                <p className="mt-1 text-[var(--lumi-text-secondary)]">
                  甲：{conflict.aQuote}
                </p>
                <p className="mt-0.5 text-[var(--lumi-text-secondary)]">
                  乙：{conflict.bQuote}
                </p>
                <p className="mt-1 text-[10px] text-[var(--lumi-text-tertiary)]">
                  证据：{conflict.aRef}#{conflict.aEvidence.blockIndex ?? '—'} ·{' '}
                  {conflict.bRef}#{conflict.bEvidence.blockIndex ?? '—'}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  )
}
