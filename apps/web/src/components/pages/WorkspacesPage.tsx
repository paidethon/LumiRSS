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
 *   顺序——真实按钮，键盘可达即排序可达）；stale 条目给「建议移除」
 *   提示；rss/library 条目有安全外链时直接可打开；
 * - 诚实状态：加载 Skeleton / 空态 / 错误重试，与书签页一致。
 */

import { useState } from 'react'
import { ArrowDown, ArrowUp, FolderOpen, Loader2, MoreVertical, Pencil, Plus, Trash2 } from 'lucide-react'
import {
  useCreateWorkspaceMutation,
  useDeleteWorkspaceMutation,
  useRemoveWorkspaceItemMutation,
  useRenameWorkspaceMutation,
  useReorderWorkspaceItemsMutation,
  useWorkspaceContents,
  useWorkspaces,
} from '../../api/queries'
import type { ResolvedItem } from '../../api/types'
import type { Workspace } from '../../api/types'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Menu } from '../ui/Menu'
import { Skeleton } from '../ui/Skeleton'
import UnifiedContentCard from '../UnifiedContentCard'
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
  const rename = useRenameWorkspaceMutation()
  const trimmed = name.trim()
  const canSubmit = trimmed !== '' && trimmed !== workspace.name && !rename.isPending

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
          <Button
            variant="primary"
            size="sm"
            disabled={!canSubmit}
            onClick={() => {
              if (!canSubmit) return
              rename.mutate(
                { workspaceId: workspace.id, name: trimmed },
                { onSuccess: onClose },
              )
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
          rename.mutate(
            { workspaceId: workspace.id, name: trimmed },
            { onSuccess: onClose },
          )
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
/** 单张内容卡 + 行内动作：上移 / 下移 / 移除。 */
function ContentCardRow({
  item,
  workspaceId,
  index,
  total,
  orderedRefs,
}: {
  item: ResolvedItem
  workspaceId: string
  index: number
  total: number
  /** 当前展示顺序的全部 itemRef（contents 返回顺序） */
  orderedRefs: string[]
}) {
  const remove = useRemoveWorkspaceItemMutation()
  const reorder = useReorderWorkspaceItemsMutation()
  const busy = remove.isPending || reorder.isPending
  const actionError = remove.error ?? reorder.error

  const move = (delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= total) return
    const next = [...orderedRefs]
    const [moved] = next.splice(index, 1)
    next.splice(target, 0, moved)
    reorder.mutate({ workspaceId, itemRefs: next })
  }

  return (
    <li>
      <UnifiedContentCard
        item={item}
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
          源已失效，无法打开原文，建议移除。
        </p>
      )}
      {(remove.isError || reorder.isError) && (
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
  // P0-10：重命名 / 删除（仅非保留工作区提供入口）。
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const wsItems = workspaces.data?.items ?? []
  const effectiveSelectedId = selectedId ?? wsItems[0]?.id ?? null
  const selectedWorkspace = wsItems.find((w) => w.id === effectiveSelectedId) ?? null

  const contents = useWorkspaceContents(effectiveSelectedId)
  const resolvedItems = contents.data?.items ?? []

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
          {selectedWorkspace !== null && !selectedWorkspace.reserved && (
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
              }}
            />
          )}
        </div>

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
        {effectiveSelectedId !== null && !workspaces.isError && (
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
    </div>
  )
}
