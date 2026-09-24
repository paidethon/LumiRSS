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
 * - N101 分组：分组视图（GET /groups）渲染为可折叠分组区（固定区在最
 *   前；未分组 = 隐式前置组）；折叠状态仅存本机（localStorage）；
 *   「移动到分组」走行内菜单（拖拽不在本里程碑）；
 * - N102 固定：行内菜单 固定/取消固定（set 语义）；固定条目移除被
 *   BFF 拒绝（409 workspace_item_pinned）→ 行内诚实提示 + 强制移除；
 * - N103 临时预览：「预览」按钮打开页内预览窗格（同刻至多一个，打开
 *   另一个 = 整体替换）；窗格含本机笔记草稿——未保存草稿拦截替换
 *   （诚实提示 + 保存/放弃）；「添加到工作区」把预览条目提升为成员；
 * - N104 最近关闭：关闭的预览与被移除的条目进入本机 LRU（20），
 *   「最近关闭」面板可恢复（恢复 = 打开预览；已打开则不重复）；
 * - N105 快照：会话快照区（保存/恢复/删除，见 WorkspaceSnapshotsPanel）；
 * - 诚实状态：加载 Skeleton / 空态 / 错误重试，与书签页一致。
 */

import { useCallback, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Eye,
  FolderOpen,
  History,
  LayoutDashboard,
  Loader2,
  MoreVertical,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Trash2,
} from 'lucide-react'
import { MarkdownImportPanel } from '../MarkdownImportPanel'
import {
  useAddWorkspaceItemMutation,
  useCreateWorkspaceMutation,
  useDeleteWorkspaceMutation,
  usePutWorkspaceResumeMutation,
  useRemoveWorkspaceItemMutation,
  useRenameWorkspaceMutation,
  useReorderWorkspaceItemsMutation,
  useSetItemGroupMutation,
  useSetItemPinnedMutation,
  useWorkspaceContents,
  useWorkspaceGroups,
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
import { WorkspaceSnapshotsPanel } from '../WorkspaceSnapshotsPanel'
import {
  PreviewDraftActions,
  PreviewDraftNotice,
  WorkspacePreviewPane,
} from '../WorkspacePreviewPane'
import type { PreviewTarget } from '../WorkspacePreviewPane'
import { isOpenable, openResolvedItem } from '../../lib/open-item'
import {
  clearRecentlyClosed,
  discardPreviewDraft,
  hasUnsavedDraft,
  loadCollapsedGroups,
  loadPreviewDraft,
  loadRecentlyClosed,
  pushRecentlyClosed,
  saveCollapsedGroups,
  savePreviewDraft,
} from '../../lib/workspace-tabs'
import type { RecentClosedItem } from '../../lib/workspace-tabs'
import type { ResolvedItem } from '../../api/types'
import type { Workspace, WorkspaceGroupsResponse } from '../../api/types'
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

/** 单张内容卡 + 行内动作：预览 / 上移 / 下移 / 菜单（固定、移动到分组、
 * 移除）。
 * P15：重排序携带 expectedRevision（If-Match 式）；409 冲突时上报页面
 * （诚实提示「已在其他设备更新，已刷新」+ 重取），绝不静默覆盖。
 * N102：移除固定条目 → 409 workspace_item_pinned → 行内诚实提示 +
 * 强制移除（force=1 显式确认），绝不静默删除用户显式固定的内容。
 * N103：预览按钮回报 onPreview（打开页内预览窗格，不导航）。
 * 条目打开时回报 onItemOpened（保存续读指针）。 */
function ContentCardRow({
  item,
  workspaceId,
  index,
  total,
  orderedRefs,
  revision,
  pinned,
  onReorderConflict,
  onItemOpened,
  onPreview,
  onMoveToGroup,
  onRemoved,
  registerEl,
}: {
  item: ResolvedItem
  workspaceId: string
  index: number
  total: number
  /** 当前展示顺序的全部 itemRef（所在分区的展示顺序） */
  orderedRefs: string[]
  /** 当前工作区 revision（workspaces 列表查询；成功后失效重取保持新鲜） */
  revision: number | undefined
  /** N102：条目是否固定。 */
  pinned: boolean
  /** 重排序 409 冲突：页面级提示 + 重取由父级处理 */
  onReorderConflict: () => void
  /** 条目被打开（默认打开路由成功后）：父级保存续读指针 */
  onItemOpened: (itemRef: string) => void
  /** N103：打开页内预览窗格（替换当前预览）。 */
  onPreview: (item: ResolvedItem) => void
  /** N101：打开「移动到分组」Dialog。 */
  onMoveToGroup: (item: ResolvedItem) => void
  /** N104：移除成功后回报（进入最近关闭 LRU）。 */
  onRemoved: (item: ResolvedItem) => void
  /** 注册 <li> DOM（续读 chip 点击时滚动定位） */
  registerEl: (el: HTMLLIElement | null) => void
}) {
  const remove = useRemoveWorkspaceItemMutation()
  const reorder = useReorderWorkspaceItemsMutation()
  const setPinned = useSetItemPinnedMutation()
  const busy = remove.isPending || reorder.isPending || setPinned.isPending
  const reorderConflicted = reorder.isError && isRevisionConflict(reorder.error)
  const removePinnedConflicted =
    remove.isError &&
    remove.error instanceof ApiError &&
    remove.error.status === 409 &&
    remove.error.type === 'workspace_item_pinned'
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
      {pinned && (
        <p className="mb-1 flex items-center gap-1 px-1 text-[11px] text-[var(--lumi-text-tertiary)]">
          <Pin aria-hidden className="size-3" />
          已固定（移除需强制确认）
        </p>
      )}
      <UnifiedContentCard
        item={item}
        onOpen={openable ? handleOpen : undefined}
        actions={
          <span className="ml-auto flex items-center gap-1">
            <IconButton
              icon={<Eye aria-hidden className="size-4" />}
              label="预览"
              size="sm"
              touch
              onClick={() => onPreview(item)}
            />
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
            <Menu
              trigger={({ triggerProps }) => (
                <IconButton
                  {...triggerProps}
                  icon={<MoreVertical aria-hidden className="size-4" />}
                  label={`「${item.title}」条目操作`}
                  size="sm"
                  touch
                />
              )}
              items={[
                {
                  key: 'pin',
                  content: (
                    <>
                      {pinned ? (
                        <PinOff aria-hidden className="mr-2 inline size-3.5" />
                      ) : (
                        <Pin aria-hidden className="mr-2 inline size-3.5" />
                      )}
                      {pinned ? '取消固定' : '固定'}
                    </>
                  ),
                },
                { key: 'move-group', content: '移动到分组…' },
                {
                  key: 'remove',
                  content: (
                    <>
                      <Trash2 aria-hidden className="mr-2 inline size-3.5" />
                      移除
                    </>
                  ),
                },
              ]}
              onSelect={(key) => {
                if (key === 'pin') {
                  setPinned.mutate({
                    workspaceId,
                    itemRef: item.ref,
                    pinned: !pinned,
                  })
                }
                if (key === 'move-group') onMoveToGroup(item)
                if (key === 'remove') {
                  remove.mutate(
                    { workspaceId, itemRef: item.ref },
                    { onSuccess: () => onRemoved(item) },
                  )
                }
              }}
            />
          </span>
        }
      />
      {removePinnedConflicted && (
        <div
          role="alert"
          data-testid="workspace-pinned-conflict"
          className="mt-1 flex flex-wrap items-center gap-2 px-1 text-xs text-[var(--lumi-text-secondary)]"
        >
          <Pin aria-hidden className="size-3.5 shrink-0" />
          <span>该条目已固定：常规移除被拒绝（需显式确认）。</span>
          <Button
            variant="danger"
            size="sm"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(
                { workspaceId, itemRef: item.ref, force: true },
                { onSuccess: () => onRemoved(item) },
              )
            }
          >
            {remove.isPending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <Trash2 aria-hidden className="size-4" />
            )}
            强制移除
          </Button>
        </div>
      )}
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
      {(remove.isError && !removePinnedConflicted) || (reorder.isError && !reorderConflicted) ? (
        actionError !== null && (
          <p role="alert" className="mt-1 px-1 text-xs text-[var(--lumi-danger)]">
            操作失败：
            {actionError instanceof Error ? actionError.message : '请稍后重试。'}
          </p>
        )
      ) : null}
    </li>
  )
}

/** N101：移动到分组 Dialog（行内菜单入口；拖拽不在本里程碑）。
 * 单选：未分组 / 既有组 / 新建分组。提交 = PATCH items/{ref}/group。 */
function MoveToGroupDialog({
  workspaceId,
  item,
  groupNames,
  currentGroup,
  onClose,
}: {
  workspaceId: string
  item: ResolvedItem
  groupNames: string[]
  currentGroup: string | null
  onClose: () => void
}) {
  const UNGROUPED = '__ungrouped__'
  const NEW_GROUP = '__new__'
  const [selected, setSelected] = useState(currentGroup ?? UNGROUPED)
  const [newName, setNewName] = useState('')
  const move = useSetItemGroupMutation()

  const targetGroup =
    selected === UNGROUPED
      ? null
      : selected === NEW_GROUP
        ? newName.trim()
        : selected
  const canSubmit = targetGroup !== null && targetGroup !== '' && !move.isPending

  return (
    <Dialog
      open
      onClose={onClose}
      title="移动到分组"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={move.isPending}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            onClick={() =>
              move.mutate(
                { workspaceId, itemRef: item.ref, groupName: targetGroup },
                { onSuccess: onClose },
              )
            }
          >
            {move.isPending ? '移动中…' : '移动'}
          </Button>
        </>
      }
    >
      <p className="mb-2 text-xs text-[var(--lumi-text-secondary)]">
        将「{item.title}」移动到：
      </p>
      <fieldset className="flex flex-col gap-1.5">
        <label className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input
            type="radio"
            name="move-group-target"
            value={UNGROUPED}
            checked={selected === UNGROUPED}
            onChange={() => setSelected(UNGROUPED)}
          />
          未分组
        </label>
        {groupNames.map((name) => (
          <label
            key={name}
            className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]"
          >
            <input
              type="radio"
              name="move-group-target"
              value={name}
              checked={selected === name}
              onChange={() => setSelected(name)}
            />
            {name}
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input
            type="radio"
            name="move-group-target"
            value={NEW_GROUP}
            checked={selected === NEW_GROUP}
            onChange={() => setSelected(NEW_GROUP)}
          />
          新建分组
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={64}
            aria-label="新分组名称"
            placeholder="组名（≤64 字）"
            onFocus={() => setSelected(NEW_GROUP)}
            className={cx(
              'min-h-7 flex-1 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-xs',
              'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
      </fieldset>
      {move.isError && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {move.error instanceof Error ? move.error.message : '移动失败，请稍后重试。'}
        </p>
      )}
    </Dialog>
  )
}

/** 空内容占位（稳定引用，供 useMemo 依赖）。 */
const EMPTY_RESOLVED_ITEMS: ResolvedItem[] = []

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
  // 稳定引用（空态复用同一常量数组）：下游 useMemo 依赖它而不必每渲染重算。
  const resolvedItems = useMemo(
    () => contents.data?.items ?? EMPTY_RESOLVED_ITEMS,
    [contents.data],
  )
  // N101：分组视图（固定区 + 未分组隐式前置组 + 命名组序列）。
  // 加载中/失败 → 诚实回退为原始顺序平铺（绝不伪造分组）。
  const groupsQuery = useWorkspaceGroups(effectiveSelectedId)
  const groupData: WorkspaceGroupsResponse | null = groupsQuery.data ?? null

  // ---- N101：分组折叠状态（仅本机 localStorage；换工作区重载） ----
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  // ---- N103：临时预览（同刻至多一个）+ 本机笔记草稿 + 拦截提示 ----
  const [preview, setPreview] = useState<PreviewTarget | null>(null)
  const [previewDraft, setPreviewDraft] = useState('')
  const [previewBlocked, setPreviewBlocked] = useState(false)
  // N103：提升动作（添加到工作区）。
  const addMember = useAddWorkspaceItemMutation()
  // ---- N104：最近关闭（本机 LRU 20） ----
  const [recentlyClosed, setRecentlyClosed] = useState<RecentClosedItem[]>(() =>
    loadRecentlyClosed(),
  )
  // N101：移动到分组 Dialog 目标。
  const [moveGroupTarget, setMoveGroupTarget] = useState<ResolvedItem | null>(null)

  // 换工作区：重载本机折叠状态 + 关闭预览（预览属于原工作区上下文）。
  const workspaceKey = effectiveSelectedId ?? ''
  const prevWorkspaceKey = useRef(workspaceKey)
  if (prevWorkspaceKey.current !== workspaceKey) {
    prevWorkspaceKey.current = workspaceKey
    // 渲染期重置（React 官方推荐的「跟随 props/state 重置」模式）：
    // localStorage 读取在渲染期一次性完成，无 effect 时序问题。
    setCollapsedGroups(loadCollapsedGroups(workspaceKey))
    setPreview(null)
    setPreviewDraft('')
    setPreviewBlocked(false)
    setMoveGroupTarget(null)
  }

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

  // ---- N103：预览打开/关闭（未保存草稿拦截替换）+ N104 最近关闭 ----

  const handlePreviewDraftChange = (text: string) => {
    setPreviewDraft(text)
    // 草稿编辑成功解除拦截（提示只在「会丢内容」的时刻有意义）。
    setPreviewBlocked(false)
  }

  const openPreview = (target: PreviewTarget) => {
    if (effectiveSelectedId === null) return
    // N103：同刻至多一个预览——当前预览有未保存草稿时拦截替换（诚实
    // 提示 + 保存/放弃出口），绝不静默丢弃用户输入。
    if (
      preview !== null &&
      hasUnsavedDraft(effectiveSelectedId, preview.ref, previewDraft)
    ) {
      setPreviewBlocked(true)
      return
    }
    setPreview(target)
    setPreviewDraft(loadPreviewDraft(effectiveSelectedId, target.ref))
    setPreviewBlocked(false)
  }

  const closePreview = () => {
    if (preview === null || effectiveSelectedId === null) return
    if (hasUnsavedDraft(effectiveSelectedId, preview.ref, previewDraft)) {
      setPreviewBlocked(true)
      return
    }
    // N104：关闭的预览进入本机最近关闭 LRU（恢复 = 重新打开预览）。
    setRecentlyClosed(
      pushRecentlyClosed({
        ref: preview.ref,
        title: preview.title,
        url: preview.url ?? null,
        workspaceId: effectiveSelectedId,
      }),
    )
    setPreview(null)
    setPreviewDraft('')
    setPreviewBlocked(false)
  }

  const saveDraft = () => {
    if (preview === null || effectiveSelectedId === null) return
    savePreviewDraft(effectiveSelectedId, preview.ref, previewDraft)
    setPreviewBlocked(false)
  }

  const discardDraft = () => {
    if (preview === null || effectiveSelectedId === null) return
    discardPreviewDraft(effectiveSelectedId, preview.ref)
    setPreviewDraft('')
    setPreviewBlocked(false)
  }

  const restoreRecentlyClosed = (entry: RecentClosedItem) => {
    // 已打开同一预览 → 不重复打开（也不重复置换）。
    if (preview?.ref === entry.ref) return
    openPreview({
      ref: entry.ref,
      title: entry.title,
      url: entry.url,
    })
  }

  // N104：条目被移出工作区（含强制移除）→ 记入最近关闭（可快速找回）。
  const handleItemRemoved = useCallback(
    (item: ResolvedItem) => {
      if (effectiveSelectedId === null) return
      setRecentlyClosed(
        pushRecentlyClosed({
          ref: item.ref,
          title: item.title,
          url: item.url ?? null,
          workspaceId: effectiveSelectedId,
        }),
      )
    },
    [effectiveSelectedId],
  )

  const toggleGroupCollapsed = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      saveCollapsedGroups(workspaceKey, next)
      return next
    })
  }

  // ---- N101：分组渲染结构（分组视图不可用时回退平铺） ----
  const memberRefs = useMemo(() => {
    const refs = new Set<string>()
    if (groupData !== null) {
      for (const item of groupData.pinned) refs.add(item.itemRef)
      for (const group of groupData.groups) {
        for (const item of group.items) refs.add(item.itemRef)
      }
    } else {
      for (const item of resolvedItems) refs.add(item.ref)
    }
    return refs
  }, [groupData, resolvedItems])

  interface GroupSection {
    key: string
    label: string
    group: string | null
    pinnedSection: boolean
    items: ResolvedItem[]
  }

  const sections: GroupSection[] = useMemo(() => {
    const resolvedByRef = new Map(resolvedItems.map((it) => [it.ref, it]))
    const pick = (refs: { itemRef: string }[]): ResolvedItem[] =>
      refs
        .map((wi) => resolvedByRef.get(wi.itemRef))
        .filter((it): it is ResolvedItem => it !== undefined)
    if (groupData === null) return []
    const result: GroupSection[] = []
    if (groupData.pinned.length > 0) {
      result.push({
        key: 'pinned',
        label: '固定',
        group: null,
        pinnedSection: true,
        items: pick(groupData.pinned),
      })
    }
    for (const group of groupData.groups) {
      result.push({
        key: group.name ?? '__ungrouped__',
        label: group.name ?? '未分组',
        group: group.name,
        pinnedSection: false,
        items: pick(group.items),
      })
    }
    return result
  }, [groupData, resolvedItems])

  const groupNames = useMemo(
    () =>
      groupData === null
        ? []
        : groupData.groups
            .map((g) => g.name)
            .filter((name): name is string => name !== null),
    [groupData],
  )

  /** 回退平铺（分组视图加载中/失败时按原始顺序渲染，行为与旧版一致）。 */
  const renderFlatRows = () =>
    resolvedItems.map((item, index) => (
      <ContentCardRow
        key={item.ref}
        item={item}
        workspaceId={effectiveSelectedId ?? ''}
        index={index}
        total={resolvedItems.length}
        orderedRefs={resolvedItems.map((it) => it.ref)}
        revision={selectedWorkspace?.revision}
        pinned={false}
        onReorderConflict={handleReorderConflict}
        onItemOpened={handleItemOpened}
        onPreview={openPreview}
        onMoveToGroup={setMoveGroupTarget}
        onRemoved={handleItemRemoved}
        registerEl={(el) => {
          if (el === null) itemEls.current.delete(item.ref)
          else itemEls.current.set(item.ref, el)
        }}
      />
    ))

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
        {/* N103：未保存草稿拦截提示（保存/放弃后可继续替换或关闭）。 */}
        {previewBlocked && preview !== null && (
          <div className="mt-3">
            <PreviewDraftNotice
              actions={<PreviewDraftActions onSave={saveDraft} onDiscard={discardDraft} />}
            />
          </div>
        )}
        {/* N103：预览窗格（同刻至多一个；打开另一个 = 整体替换）。 */}
        {preview !== null && effectiveSelectedId !== null && (
          <div className="mt-3" data-workspace-preview-slot>
            <WorkspacePreviewPane
              target={preview}
              draftText={previewDraft}
              onDraftChange={handlePreviewDraftChange}
              isMember={memberRefs.has(preview.ref)}
              promotePending={addMember.isPending}
              onPromote={() =>
                addMember.mutate({
                  workspaceId: effectiveSelectedId,
                  itemRef: preview.ref,
                })
              }
              onClose={closePreview}
            />
          </div>
        )}
        {/* N104：最近关闭（本机 LRU；恢复 = 打开预览，不导航）。 */}
        {view === 'list' && recentlyClosed.length > 0 && (
          <section
            aria-label="最近关闭"
            data-testid="workspace-recently-closed"
            className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
          >
            <div className="flex items-center gap-2">
              <h2 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
                <History aria-hidden className="size-4" />
                最近关闭
                <span className="text-xs font-normal text-[var(--lumi-text-tertiary)]">
                  本机记录 · 最多 20 条
                </span>
              </h2>
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => setRecentlyClosed(clearRecentlyClosed())}
              >
                清空
              </Button>
            </div>
            <ul className="mt-2 flex flex-col gap-1" aria-label="最近关闭条目">
              {recentlyClosed.map((entry) => (
                <li
                  key={entry.ref}
                  className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]"
                >
                  <span className="min-w-0 flex-1 truncate">{entry.title}</span>
                  <Button variant="secondary" size="sm" onClick={() => restoreRecentlyClosed(entry)}>
                    恢复
                  </Button>
                </li>
              ))}
            </ul>
          </section>
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
          ) : groupsQuery.isError ? (
            <>
              <p role="status" className="mt-3 text-xs text-[var(--lumi-text-tertiary)]">
                分组视图加载失败，已按原始顺序显示。
              </p>
              <ul className="mt-3 flex flex-col gap-2.5" aria-label="工作区内容">
                {renderFlatRows()}
              </ul>
            </>
          ) : sections.length > 0 ? (
            <div className="mt-3 flex flex-col gap-3" data-testid="workspace-grouped-list">
              {sections.map((section) => {
                const collapsed = collapsedGroups.has(section.key)
                return (
                  <section key={section.key} aria-label={`分组 ${section.label}`}>
                    <button
                      type="button"
                      data-testid={`workspace-group-toggle-${section.key}`}
                      aria-expanded={!collapsed}
                      onClick={() => toggleGroupCollapsed(section.key)}
                      className={cx(
                        'flex min-h-8 w-full items-center gap-1.5 rounded-[var(--lumi-radius-full)] px-2 text-xs',
                        'text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                        'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                      )}
                    >
                      {collapsed ? (
                        <ChevronRight aria-hidden className="size-3.5" />
                      ) : (
                        <ChevronDown aria-hidden className="size-3.5" />
                      )}
                      {section.pinnedSection && <Pin aria-hidden className="size-3.5" />}
                      <span className="font-medium text-[var(--lumi-text-primary)]">
                        {section.label}
                      </span>
                      <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[11px]">
                        {section.items.length}
                      </span>
                    </button>
                    {!collapsed && (
                      <ul
                        className="mt-2 flex flex-col gap-2.5"
                        aria-label={`分组 ${section.label} 内容`}
                      >
                        {section.items.map((item, index) => (
                          <ContentCardRow
                            key={item.ref}
                            item={item}
                            workspaceId={effectiveSelectedId}
                            index={index}
                            total={section.items.length}
                            orderedRefs={section.items.map((it) => it.ref)}
                            revision={selectedWorkspace?.revision}
                            pinned={section.pinnedSection}
                            onReorderConflict={handleReorderConflict}
                            onItemOpened={handleItemOpened}
                            onPreview={openPreview}
                            onMoveToGroup={setMoveGroupTarget}
                            onRemoved={handleItemRemoved}
                            registerEl={(el) => {
                              if (el === null) itemEls.current.delete(item.ref)
                              else itemEls.current.set(item.ref, el)
                            }}
                          />
                        ))}
                      </ul>
                    )}
                  </section>
                )
              })}
            </div>
          ) : (
            <ul className="mt-3 flex flex-col gap-2.5" aria-label="工作区内容">
              {renderFlatRows()}
            </ul>
          )
        )}
        {/* N105：会话快照区（保存 / 恢复 / 删除）。 */}
        {effectiveSelectedId !== null && !workspaces.isError && view === 'list' && (
          <WorkspaceSnapshotsPanel workspaceId={effectiveSelectedId} />
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
      {moveGroupTarget !== null && effectiveSelectedId !== null && (
        <MoveToGroupDialog
          workspaceId={effectiveSelectedId}
          item={moveGroupTarget}
          groupNames={groupNames}
          currentGroup={
            groupData?.groups.find((g) =>
              g.items.some((it) => it.itemRef === moveGroupTarget.ref),
            )?.name ?? null
          }
          onClose={() => setMoveGroupTarget(null)}
        />
      )}
    </div>
  )
}
