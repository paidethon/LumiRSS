/** WorkspaceBoard — F085 工作区看板 + F086 阅读目标卡。
 *
 * N112：五状态列（todo/reading/excerpted/needs_verification/done，各列
 * 前 50 条 + 真实总数；>50 诚实提示）。移动：桌面 HTML5 拖拽 + 每张卡的
 * 「移动到…」下拉（键盘可达）。PUT 幂等（重复设置同状态无害）。同一条目
 * 在其他工作区的状态独立（服务端按 workspace_id 隔离）。
 * 目标卡：进度 = done 去重条目数，支持编辑/删除，截止日到期诚实标注。
 * N111：目标陈述（自由文本）+ 完成条件清单——条件勾选状态是设备本机
 * （localStorage，lib/goal-conditions），服务端只存文本、绝不存勾选。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ListChecks, Pencil, Target, Trash2 } from 'lucide-react'
import {
  deleteWorkspaceGoal,
  getWorkspaceBoard,
  getWorkspaceGoal,
  putWorkspaceGoal,
  setBoardStatus,
  type BoardColumnView,
  type BoardStatus,
  type WorkspaceGoalView,
} from '../api/client'
import {
  loadCheckedConditions,
  saveCheckedConditions,
} from '../lib/goal-conditions'
import { Button } from './ui/Button'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const COLUMN_LABELS: Record<BoardStatus, string> = {
  todo: '待处理',
  reading: '阅读中',
  excerpted: '待摘录',
  needs_verification: '待验证',
  done: '已完成',
}
const BOARD_STATUSES: BoardStatus[] = [
  'todo',
  'reading',
  'excerpted',
  'needs_verification',
  'done',
]

function shortRef(itemRef: string): string {
  const tail = itemRef.slice(0, 13)
  return tail
}

export function WorkspaceGoalCard({
  workspaceId,
  onOpenList,
}: {
  workspaceId: string
  onOpenList?: () => void
}) {
  const goal = useQuery({
    queryKey: ['workspace-goal', workspaceId],
    queryFn: ({ signal }) => getWorkspaceGoal(workspaceId, signal),
  })
  const [editing, setEditing] = useState(false)
  const [target, setTarget] = useState('10')
  const [deadline, setDeadline] = useState('')
  // N111：目标陈述 + 条件清单（编辑态；一行一个条件）
  const [goalText, setGoalText] = useState('')
  const [conditionsText, setConditionsText] = useState('')
  // N111：条件勾选（设备本机）——条件清单或工作区变化时重载（渲染期
  // 重置模式，见 WorkspacesPage 同款；hook 顺序保持在早退之前）。
  const conditions = goal.data?.conditions ?? []
  const [checked, setChecked] = useState<Set<string>>(() => new Set())
  const [checkedKey, setCheckedKey] = useState('')
  const conditionsKey = `${workspaceId}\u0000${conditions.join('\u0001')}`
  if (checkedKey !== conditionsKey) {
    setCheckedKey(conditionsKey)
    setChecked(loadCheckedConditions(workspaceId, conditions))
  }
  const queryClient = useQueryClient()
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['workspace-goal', workspaceId] })
  }
  const put = useMutation({
    mutationFn: () => {
      const conditions = conditionsText
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '')
      return putWorkspaceGoal(workspaceId, Math.max(1, Number(target) || 1), deadline || null, {
        goalText: goalText.trim() === '' ? null : goalText.trim(),
        conditions,
      })
    },
    onSuccess: async () => {
      setEditing(false)
      await invalidate()
    },
  })
  const del = useMutation({
    mutationFn: () => deleteWorkspaceGoal(workspaceId),
    onSuccess: async () => {
      setEditing(false)
      await invalidate()
    },
  })

  if (goal.isPending) return <Skeleton className="h-20 w-full" />
  if (goal.isError) {
    return (
      <div role="alert" className="text-xs text-[var(--lumi-danger)]">
        目标加载失败：{goal.error instanceof Error ? goal.error.message : '请稍后重试。'}
      </div>
    )
  }
  const data: WorkspaceGoalView = goal.data
  // 既有 GET 返回完整 goal（无 exists 键）；仅 {"exists": false} 表示未设定。
  const hasGoal = data.exists === true || (data.exists === undefined && data.targetCount !== undefined)
  if (!hasGoal && !editing) {
    return (
      <div className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
        <span>还没有阅读目标。</span>
        <Button variant="ghost" size="sm" onClick={() => { setEditing(true); setTarget('10'); setDeadline(''); setGoalText(''); setConditionsText('') }}>
          设定目标
        </Button>
      </div>
    )
  }

  if (editing) {
    return (
      <div className="flex flex-wrap items-end gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3" data-goal-editor="" data-testid="goal-editor">
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">目标条数（≥1）</span>
          <input
            type="number"
            min={1}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            aria-label="目标条数"
            className="w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)]"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">截止日期（可选）</span>
          <input
            type="date"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            aria-label="截止日期"
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)]"
          />
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">目标陈述（可选）</span>
          <textarea
            value={goalText}
            onChange={(e) => setGoalText(e.target.value)}
            rows={2}
            maxLength={2000}
            aria-label="目标陈述"
            placeholder="为什么读、读到什么程度"
            className="w-full resize-y rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]"
          />
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs">
          <span className="text-[var(--lumi-text-secondary)]">完成条件（可选，一行一条）</span>
          <textarea
            value={conditionsText}
            onChange={(e) => setConditionsText(e.target.value)}
            rows={2}
            aria-label="完成条件"
            placeholder={'能复述核心论点\n写一篇摘要'}
            className="w-full resize-y rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]"
          />
        </label>
        <Button variant="primary" size="sm" disabled={put.isPending} onClick={() => put.mutate()}>
          保存
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setEditing(false)}
        >
          取消
        </Button>
        {hasGoal && (
          <Button
            variant="ghost"
            size="sm"
            disabled={del.isPending}
            onClick={() => del.mutate()}
          >
            <Trash2 aria-hidden className="mr-1 inline size-3.5" />
            删除目标
          </Button>
        )}
        {put.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {put.error instanceof Error ? put.error.message : '保存失败。'}
          </p>
        )}
      </div>
    )
  }

  const done = data.doneCount ?? 0
  const total = Math.max(1, data.targetCount ?? 1)
  const pct = Math.min(100, Math.round((done / total) * 100))
  const overdue =
    data.deadline != null && data.deadline !== '' && new Date(data.deadline).getTime() < Date.now()
  const toggleCondition = (text: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(text)) next.delete(text)
      else next.add(text)
      saveCheckedConditions(workspaceId, conditions, next)
      return next
    })
  }
  return (
    <div
      data-testid="goal-card"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-3">
        <Target aria-hidden className="size-4 shrink-0 text-[var(--lumi-accent-text)]" />
        <div className="min-w-0 flex-1">
          <p className="text-xs text-[var(--lumi-text-primary)]">
            目标 {done}/{data.targetCount} 条已完成
            {data.deadline ? (
              <span className={cx('ml-2', overdue ? 'text-[var(--lumi-danger)]' : 'text-[var(--lumi-text-tertiary)]')}>
                截止 {data.deadline}{overdue ? '（已到期）' : ''}
              </span>
            ) : null}
          </p>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={data.targetCount ?? 0}
            aria-valuenow={done}
            aria-label="阅读目标进度"
            className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-[var(--lumi-surface-selected)]"
          >
            <div className="h-full rounded-full bg-[var(--lumi-accent)]" style={{ width: `${pct}%` }} />
          </div>
        </div>
        {onOpenList && (
          <Button variant="ghost" size="sm" onClick={onOpenList}>
            尚未处理
          </Button>
        )}
        <Button variant="ghost" size="sm" aria-label="编辑目标" onClick={() => { setTarget(String(data.targetCount ?? 10)); setDeadline(data.deadline ?? ''); setGoalText(data.goalText ?? ''); setConditionsText((conditions).join('\n')); setEditing(true) }}>
          <Pencil aria-hidden className="size-3.5" />
        </Button>
      </div>
      {data.goalText ? (
        <p className="whitespace-pre-wrap text-xs text-[var(--lumi-text-secondary)]" data-testid="goal-statement">
          {data.goalText}
        </p>
      ) : null}
      {conditions.length > 0 && (
        <fieldset className="flex flex-col gap-1" data-testid="goal-conditions">
          <legend className="flex items-center gap-1 text-[11px] text-[var(--lumi-text-tertiary)]">
            <ListChecks aria-hidden className="size-3" />
            完成条件（勾选只保存在本机）
          </legend>
          {conditions.map((condition) => (
            <label key={condition} className="flex min-h-7 items-center gap-2 text-xs text-[var(--lumi-text-primary)]">
              <input
                type="checkbox"
                checked={checked.has(condition)}
                onChange={() => toggleCondition(condition)}
                aria-label={`完成条件：${condition}`}
              />
              <span className={cx('min-w-0', checked.has(condition) && 'text-[var(--lumi-text-tertiary)] line-through')}>
                {condition}
              </span>
            </label>
          ))}
        </fieldset>
      )}
    </div>
  )
}

function BoardCard({ card, workspaceId }: { card: { itemRef: string }; workspaceId: string }) {
  const queryClient = useQueryClient()
  const move = useMutation({
    mutationFn: (status: BoardStatus) => setBoardStatus(workspaceId, card.itemRef, status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspace-board', workspaceId] })
    },
  })
  return (
    <li
      draggable
      onDragStart={(e) => e.dataTransfer.setData('text/lumi-item-ref', card.itemRef)}
      data-board-card={card.itemRef}
      className="flex items-center gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-xs"
    >
      <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]" title={card.itemRef}>
        {shortRef(card.itemRef)}
      </span>
      <select
        aria-label={`移动条目 ${shortRef(card.itemRef)}`}
        value=""
        disabled={move.isPending}
        onChange={(e) => {
          const value = e.target.value
          if (value !== '') move.mutate(value as BoardStatus)
          e.target.value = ''
        }}
        className="shrink-0 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]"
      >
        <option value="">移动到…</option>
        {BOARD_STATUSES.map((s) => (
          <option key={s} value={s}>{COLUMN_LABELS[s]}</option>
        ))}
      </select>
    </li>
  )
}

export function WorkspaceBoardView({ workspaceId }: { workspaceId: string }) {
  const board = useQuery({
    queryKey: ['workspace-board', workspaceId],
    queryFn: ({ signal }) => getWorkspaceBoard(workspaceId, signal),
  })
  const queryClient = useQueryClient()

  async function dropOn(workspaceIdArg: string, status: BoardStatus, e: React.DragEvent) {
    e.preventDefault()
    const ref = e.dataTransfer.getData('text/lumi-item-ref')
    if (ref === '') return
    await setBoardStatus(workspaceIdArg, ref, status)
    await queryClient.invalidateQueries({ queryKey: ['workspace-board', workspaceIdArg] })
  }

  if (board.isPending) {
    return (
      <div className="mt-3 grid max-md:grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-2" aria-label="看板加载中">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-40 w-full" />
        ))}
      </div>
    )
  }
  if (board.isError) {
    return (
      <div role="alert" className="mt-3 text-xs text-[var(--lumi-danger)]">
        看板加载失败：{board.error instanceof Error ? board.error.message : '请稍后重试。'}
      </div>
    )
  }
  const columns: BoardColumnView[] = board.data.columns
  return (
    <div className="mt-3 flex flex-col gap-3" data-testid="workspace-board">
      <WorkspaceGoalCard workspaceId={workspaceId} />
      <div className="grid max-md:grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-2">
        {columns.map((column) => (
          <section
            key={column.status}
            data-board-column={column.status}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => void dropOn(workspaceId, column.status, e)}
            className="flex min-h-32 flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2"
            aria-label={`看板列：${COLUMN_LABELS[column.status] ?? column.status}`}
          >
            <header className="flex items-center justify-between text-xs text-[var(--lumi-text-secondary)]">
              <span className="font-medium">{COLUMN_LABELS[column.status] ?? column.status}</span>
              <span data-column-total={column.status} className="rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5">
                {column.total}
              </span>
            </header>
            {column.total > column.items.length && (
              <p className="text-[10px] text-[var(--lumi-text-tertiary)]">
                仅显示前 {column.items.length} 条（共 {column.total} 条）。
              </p>
            )}
            <ul className="flex flex-col gap-1">
              {column.items.map((card) => (
                <BoardCard key={card.itemRef} card={card} workspaceId={workspaceId} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  )
}
