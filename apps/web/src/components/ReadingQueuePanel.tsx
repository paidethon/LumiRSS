/** N041 今日必读面板 —— 服务端持久化的每日阅读队列（EntryList 工具区，
 * 与阅读预算并排）。
 *
 * - N041：按预算生成（幂等：已确认的队列绝不被再次生成/后台刷新重排；
 *   「重新生成」= force 重建，done 保留）；行内 完成（checkbox，set 语义）/
 *   上移 / 下移 / 移除；手动加入当前文章；
 * - N042：分段（段由行派生 + 服务端段顺序）：段折叠 / 段内排序 /
 *   段整体完成 / 行菜单（select）移动分段；
 * - N043：冻结快照（不可变；冻结后新项绝不进入）+ 打开冻结视图
 *   （原始成员顺序；消失 ref 诚实占位）；
 * - N044：只看未完成（默认 ON 当队列有已完成项；设备本地显式开关），
 *   已完成区可展开；过滤纯读取侧，绝不删记录；
 * - N048：连续阅读间隔（关/15s/30s/60s，设备本地）：完成一项后出现
 *   倒计时芯片「下一篇：{title}」+ 立即/取消；到 0 导航（仅活动队列流，
 *   绝不改写已读状态、绝不后台强制跳转）；取消即止；关 = 直接切换。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronRight,
  ListTodo,
  Loader2,
  Snowflake,
  Trash2,
  X,
} from 'lucide-react'
import { resolveItems } from '../api/client'
import type { QueueItemView, ResolvedItem } from '../api/types'
import {
  loadReadingQueueInterval,
  READING_QUEUE_INTERVAL_OPTIONS,
  saveReadingQueueInterval,
  type ReadingQueueIntervalSeconds,
} from '../lib/reading-queue-interval'
import {
  useAddQueueItemMutation,
  useDeleteQueueSnapshotMutation,
  useFreezeQueueMutation,
  useGenerateQueueMutation,
  useMoveQueueItemSegmentMutation,
  useQueueItemDoneMutation,
  useQueueSnapshot,
  useQueueSnapshots,
  useQueueSegmentOrderMutation,
  useReorderQueueMutation,
  useRemoveQueueItemMutation,
  useTodayQueue,
} from '../api/queries'
import { Button } from './ui/Button'
import { EmptyState } from './ui/EmptyState'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'

const BUDGET_OPTIONS = [5, 15, 30, 60] as const
const UNGROUPED_KEY = '__ungrouped__'

/** rss:<entryRef> → 裸 entryRef（阅读器打开用）；非 rss ref 返回 null。 */
function toEntryRef(itemRef: string): string | null {
  return itemRef.startsWith('rss:') ? itemRef.slice(4) : null
}

export function ReadingQueuePanel({
  onOpenEntry,
  currentItemRef,
  onClose,
}: {
  onOpenEntry?: (entryRef: string) => void
  /** 当前选中的文章（rss 裸 entryRef）——「加入当前文章」用。 */
  currentItemRef?: string | null
  onClose: () => void
}) {
  const queueQuery = useTodayQueue()
  const snapshotsQuery = useQueueSnapshots()
  const generateMutation = useGenerateQueueMutation()
  const addItemMutation = useAddQueueItemMutation()
  const removeMutation = useRemoveQueueItemMutation()
  const doneMutation = useQueueItemDoneMutation()
  const reorderMutation = useReorderQueueMutation()
  const segmentMoveMutation = useMoveQueueItemSegmentMutation()
  const segmentOrderMutation = useQueueSegmentOrderMutation()
  const freezeMutation = useFreezeQueueMutation()
  const deleteSnapshotMutation = useDeleteQueueSnapshotMutation()

  const [budget, setBudget] = useState<number>(30)
  // N044：null = 尚未显式切换（默认随数据：有已完成项 → 开）。
  const [hideDoneExplicit, setHideDoneExplicit] = useState<boolean | null>(null)
  const [completedExpanded, setCompletedExpanded] = useState(false)
  const [collapsedSegments, setCollapsedSegments] = useState<Set<string>>(new Set())
  const [freezeLabel, setFreezeLabel] = useState('')
  const [openSnapshotId, setOpenSnapshotId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  // N048：设备本地间隔设置。
  const [intervalSeconds, setIntervalSeconds] = useState<ReadingQueueIntervalSeconds>(() =>
    loadReadingQueueInterval(),
  )
  const [countdown, setCountdown] = useState<{
    entryRef: string
    title: string
    remaining: number
  } | null>(null)

  const queue = queueQuery.data ?? null
  const items = queue?.items ?? []
  const doneItems = items.filter((item) => item.status === 'done')
  const pendingItems = items.filter((item) => item.status === 'pending')
  const hideDone = hideDoneExplicit ?? (doneItems.length > 0 ? true : false)

  // N048 倒计时：每秒一跳；到 0 在回调里导航一次并清芯片（绝不改已读
  // 状态、绝不后台强制跳转——取消/卸载即终止）。
  useEffect(() => {
    if (countdown === null) return
    const timer = setTimeout(() => {
      if (countdown.remaining <= 1) {
        setCountdown(null)
        if (onOpenEntry !== undefined) onOpenEntry(countdown.entryRef)
        return
      }
      setCountdown({ ...countdown, remaining: countdown.remaining - 1 })
    }, 1000)
    return () => clearTimeout(timer)
  }, [countdown, onOpenEntry])

  function fail(error: unknown) {
    setActionError(
      error instanceof Error && error.message ? error.message : '操作失败，请稍后重试。',
    )
  }

  function generate(force: boolean) {
    setActionError(null)
    generateMutation.mutate(
      { timeBudgetMinutes: budget, force },
      {
        onSuccess: (result) => {
          if (result.generated && result.items.length === 0) return
        },
        onError: fail,
      },
    )
  }

  function addCurrent() {
    if (currentItemRef == null) return
    setActionError(null)
    addItemMutation.mutate(
      { itemRef: `rss:${currentItemRef}` },
      {
        onError: (error) => {
          const status = (error as { status?: number }).status
          fail(
            status === 409
              ? new Error('该条目今日已完成，先取消完成再加入。')
              : error,
          )
        },
      },
    )
  }

  function markDone(item: QueueItemView, done: boolean) {
    setActionError(null)
    doneMutation.mutate(
      { itemId: item.id, done },
      {
        onSuccess: () => {
          if (!done || intervalSeconds === 0) return
          // N048：完成 → 下一篇倒计时（顺序 = 队列 position）。interval
          // 关(0) = 直接切换，无芯片、不自动前进。
          const next =
            pendingItems.find((candidate) => candidate.id !== item.id && toEntryRef(candidate.itemRef) !== null) ??
            null
          if (next === null) return
          const entryRef = toEntryRef(next.itemRef)
          if (entryRef === null) return
          setCountdown({ entryRef, title: next.title ?? '下一篇', remaining: intervalSeconds })
        },
        onError: fail,
      },
    )
  }

  function moveItem(item: QueueItemView, direction: -1 | 1) {
    if (queue === null) return
    const order = items.map((row) => row.id)
    const index = order.indexOf(item.id)
    const target = index + direction
    if (index === -1 || target < 0 || target >= order.length) return
    const next = [...order]
    const tmp = next[index]!
    next[index] = next[target]!
    next[target] = tmp
    reorderMutation.mutate(next, { onError: fail })
  }

  function removeItem(item: QueueItemView) {
    setActionError(null)
    if (countdown !== null && countdown.entryRef === toEntryRef(item.itemRef)) setCountdown(null)
    removeMutation.mutate(item.id, { onError: fail })
  }

  function moveSegment(item: QueueItemView, segment: string | null) {
    setActionError(null)
    segmentMoveMutation.mutate(
      { itemId: item.id, segment },
      {
        onError: (error) => {
          const status = (error as { status?: number }).status
          fail(status === 409 ? new Error('该条目今日已完成，先取消完成再移动。') : error)
        },
      },
    )
  }

  function completeSegment(name: string | null) {
    if (queue === null) return
    const targets = items.filter(
      (row) => row.status === 'pending' && (row.segment ?? null) === name,
    )
    // 串行逐条 set（set 语义；失败由每条独立上报，不中断其余）。
    for (const row of targets) {
      doneMutation.mutate({ itemId: row.id, done: true })
    }
  }

  function toggleSegmentCollapsed(key: string) {
    setCollapsedSegments((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function moveSegmentOrder(name: string | null, direction: -1 | 1) {
    if (queue === null) return
    const named = queue.segments.filter((segment) => segment.name !== null).map((segment) => segment.name as string)
    if (name === null) return
    const index = named.indexOf(name)
    const target = index + direction
    if (index === -1 || target < 0 || target >= named.length) return
    const next = [...named]
    const tmp = next[index]!
    next[index] = next[target]!
    next[target] = tmp
    segmentOrderMutation.mutate(next, { onError: fail })
  }

  function runFreeze() {
    setActionError(null)
    freezeMutation.mutate(freezeLabel.trim() === '' ? '今日批次' : freezeLabel.trim(), {
      onSuccess: () => setFreezeLabel(''),
      onError: fail,
    })
  }

  const queueDate = queue?.queueDate ?? ''

  return (
    <section
      aria-label="今日必读"
      data-testid="reading-queue-panel"
      className="mx-4 mb-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <ListTodo aria-hidden className="size-4 text-[var(--lumi-accent-text)]" />
        <h3 className="text-sm font-semibold text-[var(--lumi-text-primary)]">今日必读</h3>
        {queueDate !== '' && (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">{queueDate}</span>
        )}
        <span className="flex-1" />
        <IconButton icon={<X aria-hidden className="size-4" />} label="关闭今日必读" onClick={onClose} />
      </div>

      {openSnapshotId !== null ? (
        <FrozenView snapshotId={openSnapshotId} onBack={() => setOpenSnapshotId(null)} />
      ) : (
        <>
          {/* 生成控件（N041） */}
          <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="生成今日队列">
            <select
              aria-label="时间预算"
              value={budget}
              onChange={(event) => setBudget(Number(event.target.value))}
              className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
            >
              {BUDGET_OPTIONS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} 分钟
                </option>
              ))}
            </select>
            <Button size="sm" variant="primary" onClick={() => generate(false)} disabled={generateMutation.isPending}>
              {generateMutation.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : '生成队列'}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => generate(true)} disabled={generateMutation.isPending}>
              重新生成
            </Button>
            {currentItemRef != null && (
              <Button size="sm" variant="secondary" onClick={addCurrent} disabled={addItemMutation.isPending}>
                加入当前文章
              </Button>
            )}
          </div>
          <p className="mt-1 text-[10px] leading-4 text-[var(--lumi-text-tertiary)]">
            生成依据：未读 + 近期，按服务端粗估装填（估读≠实际）；已确认的队列不会被再次生成或后台刷新重排；
            「重新生成」= force 重建（完成状态保留）。
          </p>
          {generateMutation.data?.notes?.map((note) => (
            <p key={note} className="mt-1 text-[10px] leading-4 text-[var(--lumi-text-tertiary)]" role="note">
              {note}
            </p>
          ))}

          {/* N048 间隔 + N044 过滤 */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--lumi-text-secondary)]">
            <label className="flex items-center gap-1">
              连续阅读间隔
              <select
                aria-label="连续阅读间隔"
                value={intervalSeconds}
                onChange={(event) => {
                  const value = Number(event.target.value) as ReadingQueueIntervalSeconds
                  setIntervalSeconds(value)
                  saveReadingQueueInterval(value)
                  if (value === 0) setCountdown(null)
                }}
                className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
              >
                {READING_QUEUE_INTERVAL_OPTIONS.map((seconds) => (
                  <option key={seconds} value={seconds}>
                    {seconds === 0 ? '关' : `${seconds} 秒`}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                aria-label="只看未完成"
                checked={hideDone}
                onChange={(event) => setHideDoneExplicit(event.target.checked)}
              />
              只看未完成
            </label>
          </div>

          {actionError !== null && (
            <p className="mt-2 text-xs text-[var(--lumi-danger-text)]" role="alert">
              {actionError}
            </p>
          )}

          {queueQuery.isPending ? (
            <div className="mt-3 flex items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
              <Loader2 aria-hidden className="size-3.5 animate-spin" /> 加载中…
            </div>
          ) : queueQuery.isError ? (
            <div className="mt-2">
              <EmptyState
                icon={<CalendarClock aria-hidden className="size-6" />}
                title="今日队列加载失败"
                description="请稍后重试。"
              />
            </div>
          ) : items.length === 0 ? (
            <div className="mt-1">
              <EmptyState
                icon={<ListTodo aria-hidden className="size-6" />}
                title="今天还没有队列"
                description="选择预算点「生成队列」，或把当前文章加进来。"
              />
            </div>
          ) : (
            <>
              <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]" role="status">
                共 {items.length} 项 · 未完成 {pendingItems.length} 项
                {queue !== null && queue.totalEstimateMinutes > 0 && (
                  <> · 估读合计约 {queue.totalEstimateMinutes} 分钟</>
                )}
              </p>

              {/* N042 分段渲染（未分组 = 隐式前置组） */}
              {queue?.segments.map((segment) => {
                const key = segment.name ?? UNGROUPED_KEY
                const visible = segment.items.filter((item) => !(hideDone && item.status === 'done'))
                if (visible.length === 0) return null
                const collapsed = collapsedSegments.has(key)
                return (
                  <div key={key} className="mt-2" data-segment={segment.name ?? ''}>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        aria-expanded={!collapsed}
                        aria-label={`${collapsed ? '展开' : '折叠'}分段「${segment.name ?? '未分组'}」`}
                        onClick={() => toggleSegmentCollapsed(key)}
                        className="flex min-h-7 items-center gap-1 rounded px-1 text-xs font-medium text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
                      >
                        {collapsed ? (
                          <ChevronRight aria-hidden className="size-3.5" />
                        ) : (
                          <ChevronDown aria-hidden className="size-3.5" />
                        )}
                        {segment.name ?? '未分组'}
                      </button>
                      <span className="text-[10px] text-[var(--lumi-text-tertiary)]">
                        {segment.items.filter((item) => item.status === 'pending').length}
                      </span>
                      <span className="flex-1" />
                      {segment.name !== null && (
                        <>
                          <IconButton
                            icon={<ArrowUp aria-hidden className="size-3" />}
                            label={`上移分段「${segment.name}」`}
                            size="sm"
                            onClick={() => moveSegmentOrder(segment.name, -1)}
                          />
                          <IconButton
                            icon={<ArrowDown aria-hidden className="size-3" />}
                            label={`下移分段「${segment.name}」`}
                            size="sm"
                            onClick={() => moveSegmentOrder(segment.name, 1)}
                          />
                          <Button size="sm" variant="ghost" onClick={() => completeSegment(segment.name)}>
                            <Check aria-hidden className="size-3" />
                            整段完成
                          </Button>
                        </>
                      )}
                    </div>
                    {!collapsed && (
                      <ul className="divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
                        {visible.map((item) => (
                          <QueueRow
                            key={item.id}
                            item={item}
                            segmentNames={queue?.segmentOrder ?? []}
                            onDone={markDone}
                            onMove={moveItem}
                            onRemove={removeItem}
                            onSegment={moveSegment}
                          />
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })}

              {/* N044 已完成区（过滤开启时可展开查看/撤销） */}
              {doneItems.length > 0 && hideDone && (
                <div className="mt-2">
                  <button
                    type="button"
                    aria-expanded={completedExpanded}
                    aria-label={completedExpanded ? '收起已完成' : '展开已完成'}
                    onClick={() => setCompletedExpanded((value) => !value)}
                    className="flex min-h-7 items-center gap-1 rounded px-1 text-xs text-[var(--lumi-text-tertiary)] hover:bg-[var(--lumi-surface-hover)]"
                  >
                    {completedExpanded ? (
                      <ChevronDown aria-hidden className="size-3.5" />
                    ) : (
                      <ChevronRight aria-hidden className="size-3.5" />
                    )}
                    已完成（{doneItems.length}）
                  </button>
                  {completedExpanded && (
                    <ul className="divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] opacity-80">
                      {doneItems.map((item) => (
                        <QueueRow
                          key={item.id}
                          item={item}
                          segmentNames={queue?.segmentOrder ?? []}
                          onDone={markDone}
                          onMove={moveItem}
                          onRemove={removeItem}
                          onSegment={moveSegment}
                        />
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </>
          )}

          {/* N043 冻结快照 */}
          <div className="mt-3 border-t border-[var(--lumi-separator)] pt-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Snowflake aria-hidden className="size-3.5 text-[var(--lumi-text-tertiary)]" />
              <input
                aria-label="冻结快照名称"
                value={freezeLabel}
                onChange={(event) => setFreezeLabel(event.target.value)}
                placeholder="冻结批次名称（默认「今日批次」）"
                className="min-h-8 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs"
              />
              <Button size="sm" variant="secondary" onClick={runFreeze} disabled={freezeMutation.isPending}>
                冻结当前队列
              </Button>
            </div>
            <p className="mt-1 text-[10px] text-[var(--lumi-text-tertiary)]">
              冻结后的批次不可变：之后加入的项不会进入，条目消失时诚实显示占位。
            </p>
            {snapshotsQuery.data !== undefined && snapshotsQuery.data.items.length > 0 && (
              <ul className="mt-1.5 space-y-1">
                {snapshotsQuery.data.items.map((snapshot) => (
                  <li key={snapshot.id} className="flex items-center gap-2 text-xs">
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">
                      {snapshot.label}
                      <span className="ml-1 text-[var(--lumi-text-tertiary)]">
                        {snapshot.itemCount} 项 · {snapshot.createdAt}
                      </span>
                    </span>
                    <Button size="sm" variant="ghost" onClick={() => setOpenSnapshotId(snapshot.id)}>
                      打开
                    </Button>
                    <IconButton
                      icon={<Trash2 aria-hidden className="size-3" />}
                      label={`删除快照「${snapshot.label}」`}
                      size="sm"
                      onClick={() => deleteSnapshotMutation.mutate(snapshot.id, { onError: fail })}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* N048 倒计时芯片 */}
      {countdown !== null && (
        <div
          role="status"
          aria-label="下一篇倒计时"
          className="mt-2 flex items-center gap-2 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent-soft)] px-2.5 py-1.5 text-xs"
          data-testid="queue-next-chip"
        >
          <span className="min-w-0 flex-1 truncate text-[var(--lumi-accent-text)]">
            下一篇：{countdown.title}（{countdown.remaining}s）
          </span>
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              const target = countdown
              setCountdown(null)
              if (onOpenEntry !== undefined) onOpenEntry(target.entryRef)
            }}
          >
            立即
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setCountdown(null)}>
            取消
          </Button>
        </div>
      )}
    </section>
  )
}

/** 队列行：完成 checkbox + 标题/估读 + 分段 select + 上移/下移/移除。 */function QueueRow({
  item,
  segmentNames,
  onDone,
  onMove,
  onRemove,
  onSegment,
}: {
  item: QueueItemView
  segmentNames: string[]
  onDone: (item: QueueItemView, done: boolean) => void
  onMove: (item: QueueItemView, direction: -1 | 1) => void
  onRemove: (item: QueueItemView) => void
  onSegment: (item: QueueItemView, segment: string | null) => void
}) {
  const label = item.title ?? item.itemRef
  const segmentOptions = useMemo(() => {
    const names = [...segmentNames]
    if (item.segment !== null && item.segment !== undefined && !names.includes(item.segment)) {
      names.push(item.segment)
    }
    return names
  }, [segmentNames, item.segment])
  return (
    <li className={cx('flex items-center gap-1.5 px-2.5 py-1.5', item.status === 'done' && 'opacity-60')}>
      <input
        type="checkbox"
        aria-label={`标记「${label}」${item.status === 'done' ? '未完成' : '完成'}`}
        checked={item.status === 'done'}
        onChange={(event) => onDone(item, event.target.checked)}
        className="size-4 shrink-0"
      />
      <span className="min-w-0 flex-1">
        <span className={cx('block truncate text-sm text-[var(--lumi-text-primary)]', item.status === 'done' && 'line-through')}>
          {item.title ?? '（条目信息不可用）'}
        </span>
        <span className="block text-xs text-[var(--lumi-text-tertiary)]">
          {item.estimateMinutes !== null ? `约 ${item.estimateMinutes} 分钟` : '估读不可用'}
          {item.segment !== null && item.segment !== undefined ? ` · ${item.segment}` : ''}
        </span>
      </span>
      <select
        aria-label={`调整「${label}」分段`}
        value={item.segment ?? ''}
        onChange={(event) => onSegment(item, event.target.value === '' ? null : event.target.value)}
        className="min-h-8 max-w-24 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1 text-xs"
      >
        <option value="">未分组</option>
        {segmentOptions.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <IconButton
        icon={<ArrowUp aria-hidden className="size-3.5" />}
        label={`上移「${label}」`}
        size="sm"
        onClick={() => onMove(item, -1)}
      />
      <IconButton
        icon={<ArrowDown aria-hidden className="size-3.5" />}
        label={`下移「${label}」`}
        size="sm"
        onClick={() => onMove(item, 1)}
      />
      <IconButton
        icon={<Trash2 aria-hidden className="size-3.5" />}
        label={`移除「${label}」`}
        size="sm"
        onClick={() => onRemove(item)}
      />
    </li>
  )
}

/** N043 冻结视图：原始成员顺序；ref 经 /resolve 解析，消失/失效 →
 * 诚实占位（绝不复活内容）。 */
function FrozenView({ snapshotId, onBack }: { snapshotId: string; onBack: () => void }) {
  const snapshotQuery = useQueueSnapshot(snapshotId)
  const [resolved, setResolved] = useState<Map<string, ResolvedItem>>(new Map())
  const [resolveFailed, setResolveFailed] = useState(false)

  const items = snapshotQuery.data?.items ?? []

  useEffect(() => {
    const data = snapshotQuery.data
    if (data === undefined || data.items.length === 0) return
    let cancelled = false
    resolveItems(data.items.map((item) => item.itemRef))
      .then((result) => {
        if (cancelled) return
        const map = new Map<string, ResolvedItem>()
        for (const item of result.items) map.set(item.ref, item)
        setResolved(map)
      })
      .catch(() => {
        if (!cancelled) setResolveFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [snapshotQuery.data])

  return (
    <div className="mt-2">
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" onClick={onBack}>
          返回今日队列
        </Button>
        {snapshotQuery.data !== undefined && (
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            冻结批次「{snapshotQuery.data.label}」（不可变 · {snapshotQuery.data.createdAt}）
          </span>
        )}
      </div>
      {snapshotQuery.isPending ? (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
          <Loader2 aria-hidden className="mr-1 inline size-3 animate-spin" /> 加载中…
        </p>
      ) : snapshotQuery.isError ? (
        <EmptyState
          icon={<Snowflake aria-hidden className="size-6" />}
          title="冻结视图加载失败"
          description="快照可能已被删除。"
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Snowflake aria-hidden className="size-6" />}
          title="空批次"
          description="冻结时队列没有未完成项。"
        />
      ) : (
        <ol className="mt-1.5 divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
          {items.map((item) => {
            const hit = resolved.get(item.itemRef)
            const usable = hit !== undefined && !hit.stale
            return (
              <li key={`${item.itemRef}-${item.position}`} className="flex items-center gap-2 px-2.5 py-1.5">
                <span className="min-w-0 flex-1">
                  {usable ? (
                    <span className="block truncate text-sm text-[var(--lumi-text-primary)]">{hit.title}</span>
                  ) : (
                    <span className="block truncate text-sm italic text-[var(--lumi-text-tertiary)]" data-testid="queue-missing-ref">
                      条目不可用（已删除或已退订）
                    </span>
                  )}
                  <span className="block text-xs text-[var(--lumi-text-tertiary)]">
                    {item.segment !== null && item.segment !== undefined ? `${item.segment} · ` : ''}第 {item.position} 位
                    {resolveFailed && !usable ? ' · 解析失败' : ''}
                  </span>
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
