/** WorkspacesPage — 工作区页（phase2 M1）。
 *
 * BFF：/api/v1/workspaces（列表 / 创建 / 重命名 / 删除）+
 * /workspaces/{id}/contents（ResolvedItem 解析视图）。本页职责：
 * - 工作区选择器：名称 + itemCount 徽标；保留工作区 read-later 固定
 *   显示「稍后读」+「保留」标记（BFF 拒绝对其删除/重命名）；
 * - 新建工作区（Dialog，POST；ApiError 内联）；
 * - P0-10：重命名 / 删除非保留工作区（PATCH / DELETE；双重确认）；
 *   保留工作区不提供这两个入口；
 * - 选中工作区的内容卡片列表（UnifiedContentCard）：移除（DELETE
 *   item，幂等契约由 BFF 承载）、上移/下移（PATCH 重排序，传完整新
 *   顺序 + expectedRevision 乐观并发——409 = 其他设备已更新：诚实提示
 *   并重取，绝不静默覆盖）；stale 条目给「建议移除」提示；rss/library
 *   条目有安全外链时直接可打开；
 * - P15 续读：打开条目即 PUT 续读指针（每工作区一个）；指针存在且指向
 *   列表内条目时显示「继续上次」chip（滚动定位 + 复用既有打开路由）；
 * - 诚实状态：加载 Skeleton / 空态 / 错误重试，与书签页一致。
 */

import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, ArrowDown, ArrowUp, FolderOpen, History, LayoutDashboard, Loader2, MoreVertical, Pencil, Plus, Trash2 } from 'lucide-react'
import { MarkdownImportPanel } from '../MarkdownImportPanel'
import {
  useCreateWorkspaceMutation,
  useDeleteWorkspaceMutation,
  usePutWorkspaceResumeMutation,
  useRemoveWorkspaceItemMutation,
  useRenameWorkspaceMutation,
  useReorderWorkspaceItemsMutation,
  useWorkspaceContents,
  useWorkspaceResume,
  useWorkspaces,
} from '../../api/queries'
import { ApiError, exportResearchPackMd, patchWorkspaceArchive } from '../../api/client'
import { WorkspaceBoardView } from '../WorkspaceBoard'
import {
  ArchivedBar,
  ResearchPackExportDialog,
  SaveAsTemplateDialog,
  TemplatesDialog,
} from '../WorkspaceExtras'
import { isOpenable, openResolvedItem } from '../../lib/open-item'
import type { ResolvedItem } from '../../api/types'
import type { Workspace } from '../../api/types'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Menu } from '../ui/Menu'
import { Skeleton } from '../ui/Skeleton'
import UnifiedContentCard from '../UnifiedContentCard'
import { staleState } from '../../lib/stale-label'
import { DOCS_LINKS } from '../../lib/docs-links'
import { cx } from '../ui/cx'

/** 新建工作区 Dialog（条件挂载；创建成功后选中新工作区）。 */
function CreateWorkspaceDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (workspaceId: string) => void
}) {
  const [name, setName] = useState('')
  const create = useCreateWorkspaceMutation()
  const canSubmit = name.trim() !== '' && !create.isPending

  return (
    <Dialog
      open
      onClose={onClose}
      title="新建工作区"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={create.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            onClick={() => {
              if (!canSubmit) return
              create.mutate(name.trim(), {
                onSuccess: (workspace) => {
                  onCreated(workspace.id)
                  onClose()
                },
              })
            }}
          >
            {create.isPending ? '创建中…' : '创建'}
          </Button>
        </>
      }
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">名称</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如：周报整理"
          aria-label="工作区名称"
          className={cx(
            'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
            'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
            'placeholder:text-[var(--lumi-text-tertiary)]',
            'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
          )}
        />
      </label>
      {create.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {create.error instanceof Error ? create.error.message : '创建失败，请稍后重试。'}
        </p>
      )}
    </Dialog>
  )
}

/** P0-10：重命名工作区 Dialog（条件挂载；Follow RenameCategoryDialog 模式：
 * 预填现名 + 就地编辑 + 空名/未变更禁用提交 + 错误内联）。 */
function RenameWorkspaceDialog({
  workspace,
  onClose,
}: {
  workspace: Workspace
  onClose: () => void
}) {
  const [name, setName] = useState(workspace.name)
  // F25：说明编辑（创建后也能补充目标/范围说明）
  const [description, setDescription] = useState(workspace.description ?? '')
  const rename = useRenameWorkspaceMutation()
  const trimmed = name.trim()
  const descriptionChanged = description !== (workspace.description ?? '')
  const canSubmit =
    (trimmed !== '' && trimmed !== workspace.name) || descriptionChanged
      ? !rename.isPending
      : false

  function submit() {
    if (!canSubmit) return
    rename.mutate(
      {
        workspaceId: workspace.id,
        name: trimmed,
        ...(descriptionChanged ? { description } : {}),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="重命名工作区"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={rename.isPending}>
            取消
          </Button>
          <Button variant="primary" size="sm" disabled={!canSubmit} onClick={submit}>
            {rename.isPending ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">名称</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={128}
            autoFocus
            aria-label="工作区名称"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
        <label className="mt-3 flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">说明（可选）</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={500}
            rows={3}
            aria-label="工作区说明"
            placeholder="这个工作区收集什么、用于什么目标"
            className={cx(
              'w-full resize-y rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
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

/** P0-10：删除工作区 Dialog（破坏性操作，双重确认——UnsubscribeDialog 模式；
 * 不做 optimistic updates）。文案只陈述确定事实：工作区被移除、条目
 * 归属解除（内容本身不删除）。 */
function DeleteWorkspaceDialog({
  workspace,
  onClose,
  onDeleted,
}: {
  workspace: Workspace
  onClose: () => void
  /** 删除成功（父级把选中回落到剩余工作区）。 */
  onDeleted: () => void
}) {
  const [stage, setStage] = useState<'confirm' | 'final'>('confirm')
  const remove = useDeleteWorkspaceMutation()
  const busy = remove.isPending

  function confirmDelete() {
    if (busy) return
    remove.mutate(workspace.id, {
      onSuccess: () => {
        onDeleted()
        onClose()
      },
    })
  }

  return (
    <Dialog
      open
      onClose={() => {
        if (!busy) onClose()
      }}
      title={stage === 'confirm' ? '删除工作区' : '再次确认'}
      footer={
        stage === 'confirm' ? (
          <>
            <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
              保留工作区
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStage('final')} disabled={busy}>
              删除工作区
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" size="sm" onClick={() => setStage('confirm')} disabled={busy}>
              返回
            </Button>
            <Button variant="danger" size="sm" onClick={confirmDelete} disabled={busy}>
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
        将删除工作区「{workspace.name}」并解除其中 {workspace.itemCount}{' '}
        个条目的归属。条目内容本身不会被删除（可重新加入其它工作区）。
      </p>
      {stage === 'final' && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
        >
          <Trash2 aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span className="min-w-0">
            <span className="block font-medium">确定要删除这个工作区吗？</span>
            <span className="mt-0.5 block text-xs opacity-80">
              此操作无法撤销；如需继续收集，可再新建同名工作区（内容不会恢复）。
            </span>
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
/** P15：该错误是否为跨设备 revision 冲突（409 workspace_revision_conflict）——
 * 页面级诚实提示 + 重取，行内不再重复报错。 */
function isRevisionConflict(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.type === 'workspace_revision_conflict'
  )
}

/** 单张内容卡 + 行内动作：上移 / 下移 / 移除。
 * P15：重排序携带 expectedRevision（If-Match 式）；409 冲突时上报页面
 * （诚实提示「已在其他设备更新，已刷新」+ 重取），绝不静默覆盖。
 * 条目打开时回报 onItemOpened（保存续读指针）。 */
function ContentCardRow({
  item,
  workspaceId,
  index,
  total,
  orderedRefs,
  revision,
  onReorderConflict,
  onItemOpened,
  registerEl,
}: {
  item: ResolvedItem
  workspaceId: string
  index: number
  total: number
  /** 当前展示顺序的全部 itemRef（contents 返回顺序） */
  orderedRefs: string[]
  /** 当前工作区 revision（workspaces 列表查询；成功后失效重取保持新鲜） */
  revision: number | undefined
  /** 重排序 409 冲突：页面级提示 + 重取由父级处理 */
  onReorderConflict: () => void
  /** 条目被打开（默认打开路由成功后）：父级保存续读指针 */
  onItemOpened: (itemRef: string) => void
  /** 注册 <li> DOM（续读 chip 点击时滚动定位） */
  registerEl: (el: HTMLLIElement | null) => void
}) {
  const remove = useRemoveWorkspaceItemMutation()
  const reorder = useReorderWorkspaceItemsMutation()
  const busy = remove.isPending || reorder.isPending
  const reorderConflicted = reorder.isError && isRevisionConflict(reorder.error)
  const actionError = remove.error ?? (reorderConflicted ? null : reorder.error)

  const move = (delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= total) return
    const next = [...orderedRefs]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    reorder.mutate(
      { workspaceId, itemRefs: next, expectedRevision: revision },
      {
        onError: (error) => {
          if (isRevisionConflict(error)) onReorderConflict()
        },
      },
    )
  }

  // P15：可打开的条目在打开时回报（PUT 续读指针）；打开路由与卡片默认
  // 行为一致（lib/open-item.ts 按 kind 路由），不改变打开语义。
  const openable = !item.stale && isOpenable(item)
  const handleOpen = () => {
    if (openResolvedItem(item)) onItemOpened(item.ref)
  }

  return (
    <li ref={registerEl} className="scroll-mt-4" data-workspace-item={item.ref}>
      <UnifiedContentCard
        item={item}
        onOpen={openable ? handleOpen : undefined}
        actions={
          <span className="ml-auto flex items-center gap-1">
            <IconButton
              icon={<ArrowUp aria-hidden className="size-4" />}
              label="上移"
              size="sm"
              touch
              disabled={index === 0 || busy}
              onClick={() => move(-1)}
            />
            <IconButton
              icon={<ArrowDown aria-hidden className="size-4" />}
              label="下移"
              size="sm"
              touch
              disabled={index === total - 1 || busy}
              onClick={() => move(1)}
            />
            <IconButton
              icon={
                remove.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Trash2 aria-hidden className="size-4" />
                )
              }
              label="移除"
              size="sm"
              touch
              disabled={remove.isPending}
              onClick={() => remove.mutate({ workspaceId, itemRef: item.ref })}
            />
          </span>
        }
      />
      {item.stale && (
        <p className="mt-1 px-1 text-xs text-[var(--lumi-text-tertiary)]">
          {staleState(item.staleReason).hint}{' '}
          <a
            href={DOCS_LINKS.troubleshootSymptoms}
            target="_blank"
            rel="noreferrer noopener"
            className="underline underline-offset-2 hover:text-[var(--lumi-text-secondary)]"
          >
            排查帮助
          </a>
        </p>
      )}
      {(remove.isError || (reorder.isError && !reorderConflicted)) && actionError !== null && (
        <p role="alert" className="mt-1 px-1 text-xs text-[var(--lumi-danger)]">
          操作失败：
          {actionError instanceof Error ? actionError.message : '请稍后重试。'}
        </p>
      )}
    </li>
  )
}

export default function WorkspacesPage() {
  const workspaces = useWorkspaces()
  // 显式选择为 null 时派生为第一个工作区（read-later 通常 position 0）——
  // 渲染期派生，不进 effect（数据到达即生效，无二次渲染）。
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  // F020：Markdown 批量入库面板开关
  const [noteImportOpen, setNoteImportOpen] = useState(false)
  // P0-10：重命名 / 删除（仅非保留工作区提供入口）。
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  // F085：列表 / 看板视图切换。
  const [view, setView] = useState<'list' | 'board'>('list')
  // F083：模板入口。F088：ZIP 导出对话框。
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false)
  const [zipExportOpen, setZipExportOpen] = useState(false)
  // F084：归档动作与错误（409 protected_workspace 诚实展示）。
  const [archiveError, setArchiveError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const archive = useMutation({
    mutationFn: (id: string) => patchWorkspaceArchive(id, true),
    onSuccess: async () => {
      setArchiveError(null)
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['workspace-archive'] })
      setSelectedId(null)
    },
    onError: (error) => {
      setArchiveError(error instanceof Error ? error.message : '归档失败，请稍后重试。')
    },
  })

  const wsItems = workspaces.data?.items ?? []
  const effectiveSelectedId = selectedId ?? wsItems[0]?.id ?? null
  // F25：选中工作区的说明（空 = 不渲染说明区）
  const selectedDescription = wsItems.find((w) => w.id === effectiveSelectedId)?.description
  const selectedWorkspace = wsItems.find((w) => w.id === effectiveSelectedId) ?? null

  const contents = useWorkspaceContents(effectiveSelectedId)
  const resolvedItems = contents.data?.items ?? []

  // ---- P15：续读指针 + 跨设备并发诚实提示 ----
  const resume = useWorkspaceResume(effectiveSelectedId)
  const putResume = usePutWorkspaceResumeMutation()
  // 409 冲突提示（页面级；重取后以服务端状态为准，绝不静默覆盖）。
  const [conflictNotice, setConflictNotice] = useState(false)
  // 已点击消费过的续读 ref（点击后 chip 收起；指针换目标后重新出现）。
  const [resumeConsumedRef, setResumeConsumedRef] = useState<string | null>(null)
  const itemEls = useRef(new Map<string, HTMLLIElement>())

  const handleItemOpened = useCallback(
    (itemRef: string) => {
      if (effectiveSelectedId === null) return
      // 打开即保存（规格允许的简单路径）；失败静默降级——指针是体验
      // 增强，不因一次 404/网络错误打断阅读动作。
      putResume.mutate({ workspaceId: effectiveSelectedId, itemRef })
    },
    [effectiveSelectedId, putResume],
  )

  const handleReorderConflict = useCallback(() => {
    setConflictNotice(true)
    void queryClient.invalidateQueries({ queryKey: ['workspace'] })
    void queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }, [queryClient])

  const resumePointer = resume.data?.pointer ?? null
  const resumeItem =
    resumePointer !== null
      ? (resolvedItems.find((it) => it.ref === resumePointer.itemRef) ?? null)
      : null
  const showResumeChip =
    view === 'list' &&
    contents.isSuccess &&
    resumePointer !== null &&
    resumeItem !== null &&
    resumeConsumedRef !== resumePointer.itemRef

  const handleResumeClick = () => {
    if (resumeItem === null) return
    setResumeConsumedRef(resumeItem.ref)
    const el = itemEls.current.get(resumeItem.ref)
    const reduceMotion =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (el !== undefined && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' })
    }
    // 复用既有打开路由（lib/open-item.ts）；打开成功也回报指针（幂等）。
    if (openResolvedItem(resumeItem)) handleItemOpened(resumeItem.ref)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 新建工作区 + （非保留工作区）重命名/删除操作 */}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">工作区</h1>
          <Button
            variant="primary"
            size="sm"
            className="ml-auto"
            onClick={() => setCreateOpen(true)}
          >
            <Plus aria-hidden className="size-4" />
            新建工作区
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setTemplatesOpen(true)}>
            模板
          </Button>
          {selectedWorkspace !== null && (
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={view === 'board'}
              onClick={() => setView((v) => (v === 'board' ? 'list' : 'board'))}
            >
              <LayoutDashboard aria-hidden className="size-4" />
              看板
            </Button>
          )}
          {selectedWorkspace !== null && !selectedWorkspace.reserved && (
            <>
            <button
                type="button"
                aria-pressed={noteImportOpen}
                onClick={() => setNoteImportOpen((v) => !v)}
                className="min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
              >
                导入 Markdown
              </button>
              <Menu
              trigger={({ triggerProps }) => (
                <IconButton
                  {...triggerProps}
                  icon={<MoreVertical aria-hidden className="size-4" />}
                  label={`「${selectedWorkspace.name}」操作`}
                  size="sm"
                  touch
                />
              )}
              items={[
                { key: 'rename', content: (
                  <>
                    <Pencil aria-hidden className="mr-2 inline size-3.5" />
                    重命名
                  </>
                ) },
                { key: 'export', content: '导出研究包（Markdown）' },
                { key: 'export-zip', content: '导出研究包（ZIP，含快照）' },
                { key: 'save-template', content: '保存为模板' },
                { key: 'archive', content: (
                  <>
                    <Archive aria-hidden className="mr-2 inline size-3.5" />
                    归档工作区
                  </>
                ) },
                { key: 'delete', content: (
                  <>
                    <Trash2 aria-hidden className="mr-2 inline size-3.5" />
                    删除工作区
                  </>
                ) },
              ]}
              onSelect={(key) => {
                if (key === 'rename') setRenameOpen(true)
                if (key === 'delete') setDeleteOpen(true)
                if (key === 'save-template') setSaveTemplateOpen(true)
                if (key === 'export-zip') setZipExportOpen(true)
                if (key === 'archive') archive.mutate(selectedWorkspace.id)
                if (key === 'export') {
                  void exportResearchPackMd(selectedWorkspace.id).then((text) => {
                    const blob = new Blob([text], { type: 'text/markdown' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `research-pack-${selectedWorkspace.id}.md`
                    a.click()
                    URL.revokeObjectURL(url)
                  })
                }
              }}
            />
            </>
          )}
        </div>
        {noteImportOpen && <MarkdownImportPanel onClose={() => setNoteImportOpen(false)} />}
        {/* F084：归档列表入口（默认导航隐藏，此处显式可见 + 恢复）。 */}
        <ArchivedBar />
        {archiveError !== null && (
          <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">{archiveError}</p>
        )}

        {/* 工作区选择器 */}
        {workspaces.isPending ? (
          <div className="mt-2.5 flex flex-wrap gap-1.5" aria-label="工作区加载中">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-24" />
            ))}
          </div>
        ) : workspaces.isError ? (
          <div className="mt-4" role="alert">
            <EmptyState
              icon={<FolderOpen aria-hidden className="size-8" />}
              title="工作区加载失败"
              description={
                workspaces.error instanceof Error ? workspaces.error.message : '请稍后重试。'
              }
            />
            <div className="flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => workspaces.refetch()}>
                重试
              </Button>
            </div>
          </div>
        ) : (
          <div
            role="group"
            aria-label="工作区列表"
            className="mt-2.5 flex flex-wrap items-center gap-1.5"
          >
            {wsItems.map((w) => {
              const selected = effectiveSelectedId === w.id
              return (
                <button
                  key={w.id}
                  type="button"
                  data-workspace-id={w.id}
                  onClick={() => setSelectedId(w.id)}
                  aria-pressed={selected}
                  className={cx(
                    'flex min-h-8 items-center gap-1.5 rounded-[var(--lumi-radius-full)] px-2.5 py-1 text-xs',
                    'transition-colors duration-[var(--lumi-motion-fast)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    selected
                      ? 'bg-[var(--lumi-accent-soft)] font-medium text-[var(--lumi-accent-text)]'
                      : 'border border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
                  )}
                >
                  <span className="max-w-40 truncate">{w.reserved ? '稍后读' : w.name}</span>
                  {w.reserved && (
                    <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                      保留
                    </span>
                  )}
                  <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]">
                    {w.itemCount}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        {/* 选中工作区的内容 */}
        {effectiveSelectedId !== null && !workspaces.isError && selectedDescription ? (
          <p className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2 text-xs text-[var(--lumi-text-secondary)]" data-workspace-description>
            {selectedDescription}
          </p>
        ) : null}
        {/* P15：跨设备冲突诚实提示（409 后已重取，内容以服务端为准）。 */}
        {conflictNotice && (
          <div
            role="status"
            data-workspace-conflict-notice
            className="mt-2 flex items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-xs text-[var(--lumi-text-secondary)]"
          >
            <History aria-hidden className="size-3.5 shrink-0" />
            <span>提示：工作区已在其他设备更新，已刷新</span>
            <button
              type="button"
              onClick={() => setConflictNotice(false)}
              className={cx(
                'ml-auto min-h-7 rounded-[var(--lumi-radius-full)] px-2.5 text-xs text-[var(--lumi-text-secondary)]',
                'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
              )}
            >
              知道了
            </button>
          </div>
        )}
        {/* P15：续读 chip —— 指针指向的条目仍在列表中时显示；stale/已移除
            则诚实隐藏（不假装可跳转）。 */}
        {showResumeChip && resumeItem !== null && (
          <button
            type="button"
            data-workspace-resume-chip
            onClick={handleResumeClick}
            className={cx(
              'mt-3 flex min-h-8 max-w-full items-center gap-1.5 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs',
              'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            )}
          >
            <History aria-hidden className="size-3.5 shrink-0" />
            <span className="truncate">
              继续上次：<span className="font-medium">{resumeItem.title}</span>
            </span>
          </button>
        )}
        {/* 选中工作区的内容：看板（F085/F086）或列表 */}
        {effectiveSelectedId !== null && !workspaces.isError && view === 'board' ? (
          <WorkspaceBoardView workspaceId={effectiveSelectedId} />
        ) : effectiveSelectedId !== null && !workspaces.isError && (
          contents.isPending ? (
            <ul className="mt-3 flex flex-col gap-2" aria-label="工作区内容加载中">
              {Array.from({ length: 3 }, (_, i) => (
                <li key={i}>
                  <Skeleton className="h-24 w-full" />
                </li>
              ))}
            </ul>
          ) : contents.isError ? (
            <div className="mt-6" role="alert">
              <EmptyState
                icon={<FolderOpen aria-hidden className="size-8" />}
                title="内容加载失败"
                description={
                  contents.error instanceof Error ? contents.error.message : '请稍后重试。'
                }
              />
              <div className="flex justify-center">
                <Button variant="secondary" size="sm" onClick={() => contents.refetch()}>
                  重试
                </Button>
              </div>
            </div>
          ) : resolvedItems.length === 0 ? (
            <div className="mt-8">
              <EmptyState
                icon={<FolderOpen aria-hidden className="size-8" />}
                title="此工作区还没有内容"
                description="阅读时通过文章操作菜单「添加到工作区」把内容加入这里。"
              />
            </div>
          ) : (
            <ul className="mt-3 flex flex-col gap-2.5" aria-label="工作区内容">
              {resolvedItems.map((item, index) => (
                <ContentCardRow
                  key={item.ref}
                  item={item}
                  workspaceId={effectiveSelectedId}
                  index={index}
                  total={resolvedItems.length}
                  orderedRefs={resolvedItems.map((it) => it.ref)}
                  revision={selectedWorkspace?.revision}
                  onReorderConflict={handleReorderConflict}
                  onItemOpened={handleItemOpened}
                  registerEl={(el) => {
                    if (el === null) itemEls.current.delete(item.ref)
                    else itemEls.current.set(item.ref, el)
                  }}
                />
              ))}
            </ul>
          )
        )}
      </div>
      {createOpen && (
        <CreateWorkspaceDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(id) => setSelectedId(id)}
        />
      )}
      {renameOpen && selectedWorkspace !== null && (
        <RenameWorkspaceDialog
          workspace={selectedWorkspace}
          onClose={() => setRenameOpen(false)}
        />
      )}
      {deleteOpen && selectedWorkspace !== null && (
        <DeleteWorkspaceDialog
          workspace={selectedWorkspace}
          onClose={() => setDeleteOpen(false)}
          onDeleted={() => setSelectedId(null)}
        />
      )}
      {templatesOpen && (
        <TemplatesDialog onClose={() => setTemplatesOpen(false)} onCreated={(id) => setSelectedId(id)} />
      )}
      {saveTemplateOpen && selectedWorkspace !== null && (
        <SaveAsTemplateDialog workspaceId={selectedWorkspace.id} onClose={() => setSaveTemplateOpen(false)} />
      )}
      {zipExportOpen && selectedWorkspace !== null && (
        <ResearchPackExportDialog workspaceId={selectedWorkspace.id} onClose={() => setZipExportOpen(false)} />
      )}
    </div>
  )
}
