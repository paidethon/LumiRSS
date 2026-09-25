/** WorkspaceSnapshotsPanel — N105 工作区会话快照区。
 *
 * - 保存：名称输入 + 捕获当前标签页/分组状态（POST snapshots）；
 * - 列表：快照名 + 捕获时间 + 条目数（新→旧）；
 * - 恢复：Dialog 选择模式——「重组」只重排既有成员（快照外保留）、
 *   「替换」移除快照外成员（N102 固定保护：遇固定条目 409
 *   workspace_item_pinned → 诚实提示 + 「强制恢复」重试）；
 *   恢复成功展示 diff 摘要（已恢复/缺失/保留/移除——缺失条目已不在
 *   工作区，绝不复活）；
 * - 删除：Dialog 二次确认；
 * - N115 对比：先点一个快照的「对比」设为基准，再点另一个快照的
 *   「与基准对比」→ 只读差异视图（added/removed/moved/groupChanges；
 *   ref 定位走既有 views/resolve，本视图绝不解析内容）。
 * 诚实状态：加载 Skeleton / 空态 / 错误重试，与工作区页一致。
 */

import { useState } from 'react'
import { Camera, Diff, History, Loader2, RotateCcw, Trash2 } from 'lucide-react'
import {
  useCaptureWorkspaceSnapshotMutation,
  useDeleteWorkspaceSnapshotMutation,
  useRestoreWorkspaceSnapshotMutation,
  useWorkspaceSessionSnapshots,
  useWorkspaceSnapshotDiff,
} from '../api/queries'
import { ApiError } from '../api/client'
import type {
  WorkspaceSnapshot,
  WorkspaceSnapshotRestoreResult,
} from '../api/types'
import { formatPublishedAt } from '../lib/date-format'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

function isPinnedConflict(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.type === 'workspace_item_pinned'
  )
}

/** 恢复 Dialog：模式选择 + 固定冲突诚实重试。 */
function RestoreSnapshotDialog({
  workspaceId,
  snapshot,
  onClose,
  onRestored,
}: {
  workspaceId: string
  snapshot: WorkspaceSnapshot
  onClose: () => void
  onRestored: (result: WorkspaceSnapshotRestoreResult) => void
}) {
  const [mode, setMode] = useState<'reorder' | 'replace'>('reorder')
  const [force, setForce] = useState(false)
  const restore = useRestoreWorkspaceSnapshotMutation()
  const pinnedConflict =
    restore.isError && isPinnedConflict(restore.error) && !force

  function submit() {
    if (restore.isPending) return
    restore.mutate(
      { workspaceId, snapshotId: snapshot.id, mode, force },
      {
        onSuccess: (result) => {
          onRestored(result)
          onClose()
        },
      },
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`恢复快照「${snapshot.name}」`}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={restore.isPending}>
            取消
          </Button>
          <Button
            variant={mode === 'replace' && force ? 'danger' : 'primary'}
            size="sm"
            disabled={restore.isPending}
            onClick={submit}
          >
            {restore.isPending ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                恢复中…
              </>
            ) : (
              <>
                <RotateCcw aria-hidden className="size-4" />
                恢复
              </>
            )}
          </Button>
        </>
      }
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs text-[var(--lumi-text-secondary)]">恢复方式</legend>
        <label className="flex items-start gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input
            type="radio"
            name="snapshot-restore-mode"
            value="reorder"
            checked={mode === 'reorder'}
            onChange={() => setMode('reorder')}
            className="mt-1"
          />
          <span>
            重组（推荐）
            <span className="block text-xs text-[var(--lumi-text-secondary)]">
              按快照重排/重分组/重固定既有条目；快照中已消失的条目不会复活，
              快照之外的条目原样保留。
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm text-[var(--lumi-text-primary)]">
          <input
            type="radio"
            name="snapshot-restore-mode"
            value="replace"
            checked={mode === 'replace'}
            onChange={() => setMode('replace')}
            className="mt-1"
          />
          <span>
            替换
            <span className="block text-xs text-[var(--lumi-text-secondary)]">
              快照之外的条目会被移出工作区（内容本身不删除）；固定条目受保护，
              需要强制确认。
            </span>
          </span>
        </label>
      </fieldset>
      {pinnedConflict && (
        <label className="mt-3 flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2 text-xs text-[var(--lumi-danger)]">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            快照之外存在固定条目，常规恢复已被拒绝（409
            workspace_item_pinned）。勾选表示确认连固定条目一起移出。
          </span>
        </label>
      )}
      {restore.isError && !pinnedConflict && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {restore.error instanceof Error ? restore.error.message : '恢复失败，请稍后重试。'}
        </p>
      )}
    </Dialog>
  )
}

/** N115：两快照差异 Dialog（只读；方向 = 基准 → 目标）。 */
function SnapshotDiffDialog({
  workspaceId,
  base,
  target,
  onClose,
}: {
  workspaceId: string
  base: WorkspaceSnapshot
  target: WorkspaceSnapshot
  onClose: () => void
}) {
  const diff = useWorkspaceSnapshotDiff(workspaceId, base.id, target.id)

  return (
    <Dialog
      open
      onClose={onClose}
      title={`快照对比：「${base.name}」→「${target.name}」`}
      panelClassName="max-w-xl"
    >
      <div className="flex flex-col gap-2" data-testid="workspace-snapshot-diff">
        <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
          只读差异 · 条目以引用列出，点开条目可定位原文（走既有解析视图）。
        </p>
        {diff.isPending && <Skeleton className="h-24 w-full" />}
        {diff.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {diff.error instanceof Error ? diff.error.message : '差异加载失败，请稍后重试。'}
          </p>
        )}
        {diff.data !== undefined && (
          <>
            {diff.data.added.length === 0 &&
              diff.data.removed.length === 0 &&
              diff.data.moved.length === 0 &&
              diff.data.groupChanges.length === 0 && (
                <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
                  两个快照的成员与排序完全一致。
                </p>
              )}
            {diff.data.added.length > 0 && (
              <section aria-label="新增条目" data-diff-added="">
                <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">
                  新增（目标有、基准无）· {diff.data.added.length}
                </h4>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {diff.data.added.map((ref) => (
                    <li key={ref} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                      <code className="text-[10px]">{ref}</code>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {diff.data.removed.length > 0 && (
              <section aria-label="移除条目" data-diff-removed="">
                <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">
                  移除（基准有、目标无）· {diff.data.removed.length}
                </h4>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {diff.data.removed.map((ref) => (
                    <li key={ref} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                      <code className="text-[10px]">{ref}</code>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {diff.data.moved.length > 0 && (
              <section aria-label="位置变化" data-diff-moved="">
                <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">
                  位置变化 · {diff.data.moved.length}
                </h4>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {diff.data.moved.map((move) => (
                    <li key={move.ref} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                      <code className="text-[10px]">{move.ref}</code> · 第 {move.fromPos} → 第{' '}
                      {move.toPos}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {diff.data.groupChanges.length > 0 && (
              <section aria-label="分组变化" data-diff-groups="">
                <h4 className="text-xs font-semibold text-[var(--lumi-text-primary)]">
                  分组变化 · {diff.data.groupChanges.length}
                </h4>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {diff.data.groupChanges.map((change) => (
                    <li key={change.ref} className="truncate text-xs text-[var(--lumi-text-secondary)]">
                      <code className="text-[10px]">{change.ref}</code> ·{' '}
                      {change.from ?? '未分组'} → {change.to ?? '未分组'}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </Dialog>
  )
}

export function WorkspaceSnapshotsPanel({ workspaceId }: { workspaceId: string }) {
  const snapshots = useWorkspaceSessionSnapshots(workspaceId)
  const capture = useCaptureWorkspaceSnapshotMutation()
  const removeSnapshot = useDeleteWorkspaceSnapshotMutation()
  const [name, setName] = useState('')
  // 恢复 / 删除的目标（条件挂载 Dialog）。
  const [restoreTarget, setRestoreTarget] = useState<WorkspaceSnapshot | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<WorkspaceSnapshot | null>(null)
  // N115：对比基准 + 对比目标（null = 未进入对比流）。
  const [diffBase, setDiffBase] = useState<WorkspaceSnapshot | null>(null)
  const [diffTarget, setDiffTarget] = useState<WorkspaceSnapshot | null>(null)
  // 最近一次恢复的 diff 摘要（诚实展示：缺失/保留/移除）。
  const [lastResult, setLastResult] = useState<
    (WorkspaceSnapshotRestoreResult & { snapshotName: string }) | null
  >(null)

  const canCapture = name.trim() !== '' && !capture.isPending

  return (
    <section
      data-workspace-snapshots
      aria-label="工作区快照"
      className="mt-4 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
          <History aria-hidden className="size-4" />
          会话快照
        </h2>
        <form
          className="ml-auto flex items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!canCapture) return
            capture.mutate(
              { workspaceId, name: name.trim() },
              { onSuccess: () => setName('') },
            )
          }}
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            aria-label="快照名称"
            placeholder="例如：周五整理前"
            className={cx(
              'min-h-7 w-40 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-xs',
              'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
          <Button type="submit" variant="secondary" size="sm" disabled={!canCapture}>
            {capture.isPending ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <Camera aria-hidden className="size-4" />
            )}
            保存快照
          </Button>
        </form>
      </div>
      {capture.isError && (
        <p role="alert" className="mt-1.5 text-xs text-[var(--lumi-danger)]">
          {capture.error instanceof Error ? capture.error.message : '保存失败，请稍后重试。'}
        </p>
      )}
      {lastResult !== null && (
        <p
          role="status"
          data-testid="workspace-restore-result"
          className="mt-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
        >
          已恢复快照「{lastResult.snapshotName}」：恢复 {lastResult.restored} 条
          {lastResult.missing.length > 0 && ` · 缺失 ${lastResult.missing.length} 条（未复活）`}
          {lastResult.kept > 0 && ` · 保留 ${lastResult.kept} 条`}
          {lastResult.removed.length > 0 && ` · 移除 ${lastResult.removed.length} 条`}
        </p>
      )}

      {snapshots.isPending ? (
        <div className="mt-2 flex flex-col gap-1.5">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : snapshots.isError ? (
        <div className="mt-2" role="alert">
          <p className="text-xs text-[var(--lumi-danger)]">
            {snapshots.error instanceof Error ? snapshots.error.message : '快照加载失败。'}
          </p>
          <Button variant="secondary" size="sm" onClick={() => snapshots.refetch()}>
            重试
          </Button>
        </div>
      ) : snapshots.data.items.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
          还没有快照。整理前保存一份，随时可以按名字恢复当天的分组与顺序。
        </p>
      ) : (
        <>
        <ul className="mt-2 flex flex-col gap-1.5" aria-label="快照列表">
          {snapshots.data.items.map((snapshot) => (
            <li
              key={snapshot.id}
              className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5"
              data-testid={`workspace-snapshot-${snapshot.id}`}
            >
              <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-primary)]">
                {snapshot.name}
                <span className="ml-2 text-[var(--lumi-text-tertiary)]">
                  {snapshot.itemCount} 条 · {formatPublishedAt(snapshot.createdAt)}
                </span>
              </span>
              {diffBase !== null && diffBase.id !== snapshot.id && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setDiffTarget(snapshot)}
                >
                  <Diff aria-hidden className="size-4" />
                  与「{diffBase.name}」对比
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                aria-pressed={diffBase?.id === snapshot.id}
                onClick={() => {
                  setDiffBase((prev) => (prev?.id === snapshot.id ? null : snapshot))
                  setDiffTarget(null)
                }}
              >
                <Diff aria-hidden className="size-4" />
                {diffBase?.id === snapshot.id ? '取消基准' : '设为对比基准'}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setRestoreTarget(snapshot)}
              >
                恢复
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={removeSnapshot.isPending}
                onClick={() => setDeleteTarget(snapshot)}
              >
                <Trash2 aria-hidden className="size-4" />
                删除
              </Button>
            </li>
          ))}
        </ul>
        {diffBase !== null && (
          <p className="mt-1.5 text-[11px] text-[var(--lumi-text-tertiary)]" role="status">
            已选基准「{diffBase.name}」——再点另一个快照的「与基准对比」查看差异。
          </p>
        )}
        </>
      )}
      {deleteTarget !== null && (
        <Dialog
          open
          onClose={() => setDeleteTarget(null)}
          title="删除快照"
          footer={
            <>
              <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>
                保留
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={removeSnapshot.isPending}
                onClick={() =>
                  removeSnapshot.mutate(
                    { workspaceId, snapshotId: deleteTarget.id },
                    { onSuccess: () => {
                      if (
                        lastResult !== null &&
                        lastResult.snapshotName === deleteTarget.name
                      ) {
                        setLastResult(null)
                      }
                      setDeleteTarget(null)
                    } },
                  )
                }
              >
                {removeSnapshot.isPending ? '删除中…' : '确认删除'}
              </Button>
            </>
          }
        >
          <p className="text-sm text-[var(--lumi-text-secondary)]">
            将删除快照「{deleteTarget.name}」（{deleteTarget.itemCount} 条记录）。
            工作区当前内容不受影响；删除后无法再用它恢复。
          </p>
          {removeSnapshot.isError && (
            <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
              {removeSnapshot.error instanceof Error
                ? removeSnapshot.error.message
                : '删除失败，请稍后重试。'}
            </p>
          )}
        </Dialog>
      )}
      {restoreTarget !== null && (
        <RestoreSnapshotDialog
          workspaceId={workspaceId}
          snapshot={restoreTarget}
          onClose={() => setRestoreTarget(null)}
          onRestored={(result) =>
            setLastResult({ ...result, snapshotName: restoreTarget.name })
          }
        />
      )}
      {diffBase !== null && diffTarget !== null && (
        <SnapshotDiffDialog
          workspaceId={workspaceId}
          base={diffBase}
          target={diffTarget}
          onClose={() => setDiffTarget(null)}
        />
      )}
    </section>
  )
}
