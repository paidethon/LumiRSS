/** ReadingGestureTraining — NEW-351 阅读手势训练页（设置 → 通用 → 手势）。
 *
 * 在**合成文章**上演练当前支持的滑动与返回动作：
 * - 左缘侧滑返回：用 lib/edge-swipe 的**同一套纯函数**（起点/意图/
 *   提交阈值/预览偏移）在训练区内的合成文章上重演判定，台账只记录
 *   「会返回(练习)」，绝不真的调用 goBack；
 * - 「启用哪些手势」：直接读写既有设置键（swipeBackGesture /
 *   cardSwipeAction，与真实手势同一事实源）——本组件不建第二份存储；
 * - 合成文章有明确的「练习用合成文章」标注，与真实内容可区分。
 *
 * Base UI Dialog 承担焦点陷阱 / Escape / 滚动锁。 */

import { useRef, useState } from 'react'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { Switch } from '../ui/Switch'
import { useAppSettings, type CardSwipeAction } from '../../store/app-settings'
import {
  EDGE_SWIPE_COMMIT_PX,
  EDGE_SWIPE_INTENT_PX,
  EDGE_SWIPE_START_PX,
  previewOffset,
  swipeIntentMet,
  swipeShouldCommit,
  swipeStartCandidate,
} from '../../lib/edge-swipe'
import { SWIPE_ACTION_LABELS } from '../../lib/card-swipe'

/** 演练台账容量（防刷屏；与触控练习区同量级）。 */
export const TRAINING_LEDGER_CAP = 20

/** 卡片滑动动作全集（与设置中心的 select 同源；'none' = 关闭）。 */
export const CARD_SWIPE_TRAINING_OPTIONS: ReadonlyArray<{ value: CardSwipeAction; label: string }> = [
  { value: 'none', label: '无（关闭）' },
  { value: 'read', label: '标为已读' },
  { value: 'readLater', label: '加入稍后读' },
  { value: 'star', label: '收藏' },
]

interface LedgerEntry {
  id: number
  text: string
}

let ledgerSeq = 0

function nextLedgerId(): number {
  ledgerSeq += 1
  return ledgerSeq
}

/** 纯判定：一次边缘滑动手势在训练台的结论文案（与 EdgeSwipeBack 同一
 * 阈值语义；返回 null = 未成手势，无台账）。 */
export function edgeSwipeTrainingVerdict(input: {
  startX: number
  dx: number
  dy: number
  elapsedMs: number
}): string | null {
  if (!swipeStartCandidate(input.startX)) return null
  if (!swipeIntentMet(input.dx, input.dy)) return null
  if (swipeShouldCommit(input.dx, input.elapsedMs)) return '触发:左缘侧滑返回(练习)'
  return `预览中（位移 ${previewOffset(input.dx)}px，≥${EDGE_SWIPE_COMMIT_PX}px 提交）`
}

/** 合成文章演练台：左缘滑动手势重演（只记账，绝不 goBack）。 */
function EdgeSwipePracticeCard({ onVerdict }: { onVerdict: (text: string) => void }) {
  const [previewDx, setPreviewDx] = useState(0)
  const startRef = useRef<{ x: number; y: number; t: number } | null>(null)

  const onTouchStart = (event: React.TouchEvent) => {
    const touch = event.touches[0]
    if (!touch) return
    startRef.current = { x: touch.clientX, y: touch.clientY, t: Date.now() }
  }

  const onTouchMove = (event: React.TouchEvent) => {
    const start = startRef.current
    const touch = event.touches[0]
    if (start === null || !touch) return
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    if (!swipeIntentMet(dx, dy)) return
    setPreviewDx(previewOffset(dx))
  }

  const onTouchEnd = (event: React.TouchEvent) => {
    const start = startRef.current
    startRef.current = null
    setPreviewDx(0)
    if (start === null) return
    const touch = event.changedTouches[0]
    const dx = touch !== undefined ? touch.clientX - start.x : 0
    const dy = touch !== undefined ? touch.clientY - start.y : 0
    const verdict = edgeSwipeTrainingVerdict({
      startX: start.x,
      dx,
      dy,
      elapsedMs: Date.now() - start.t,
    })
    if (verdict !== null) onVerdict(verdict)
  }

  const onTouchCancel = () => {
    startRef.current = null
    setPreviewDx(0)
  }

  return (
    <div className="relative overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
      {previewDx > 0 && (
        <div
          aria-hidden="true"
          data-n351-swipe-hint=""
          className="pointer-events-none absolute inset-y-0 left-0 flex items-center bg-[var(--lumi-accent-soft)] px-4 text-xs font-medium text-[var(--lumi-accent-text)]"
          style={{ width: Math.min(previewDx, 120) }}
        >
          返回
        </div>
      )}
      <div
        data-testid="n351-edge-swipe-practice"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchCancel}
        className="relative min-h-28 bg-[var(--lumi-surface)] px-4 py-3"
        style={previewDx > 0 ? { transform: `translateX(${previewDx}px)` } : undefined}
      >
        <p className="text-xs font-medium text-[var(--lumi-text-tertiary)]" data-n351-synthetic-label="">
          练习用合成文章（非真实内容）
        </p>
        <p className="mt-1 text-sm font-medium leading-relaxed text-[var(--lumi-text-primary)]">
          合成文章：从左侧边缘向右滑动以练习返回
        </p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          起点 ≤{EDGE_SWIPE_START_PX}px · 横向意图 &gt;{EDGE_SWIPE_INTENT_PX}px · 提交 ≥
          {EDGE_SWIPE_COMMIT_PX}px。这里只会记入台账，绝不真的返回。
        </p>
      </div>
    </div>
  )
}

/** 训练页浮层。 */
export function ReadingGestureTrainingOverlay({ onClose }: { onClose: () => void }) {
  const swipeBackGesture = useAppSettings((s) => s.settings.swipeBackGesture)
  const cardSwipeAction = useAppSettings((s) => s.settings.cardSwipeAction)
  const updateSettings = useAppSettings((s) => s.update)
  const [ledger, setLedger] = useState<LedgerEntry[]>([])

  const pushEntry = (text: string) => {
    setLedger((prev) => [{ id: nextLedgerId(), text }, ...prev].slice(0, TRAINING_LEDGER_CAP))
  }

  return (
    <Dialog open onClose={onClose} title="阅读手势训练" panelClassName="max-w-xl">
      <div className="flex flex-col gap-4">
        <p className="text-xs leading-5 text-[var(--lumi-text-secondary)]">
          在合成文章上演练当前支持的滑动与返回动作；所有动作只写入台账，
          不改动真实内容。启用选择与真实手势读写同一份设置。
        </p>

        {/* 启用哪些手势（同一设置键，无第二份存储） */}
        <section aria-label="手势启用" className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">启用哪些手势</h3>
          <div
            data-n351-gesture-row="edge-swipe-back"
            className="flex items-center justify-between gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">左缘侧滑返回</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                移动端视口 · 任意页面左缘 ≤20px。与浏览器原生边缘返回互让。
              </p>
            </div>
            <Switch
              label="启用左缘侧滑返回"
              checked={swipeBackGesture}
              onCheckedChange={(v) => updateSettings({ swipeBackGesture: v })}
            />
          </div>
          <div className="flex items-center justify-between gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 py-2">
            <div className="min-w-0">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">卡片滑动动作</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                列表卡片上的滑动动作（选「无」即关闭）。
              </p>
            </div>
            <label className="shrink-0">
              <span className="sr-only">选择卡片滑动动作</span>
              <select
                data-testid="n351-card-swipe-select"
                aria-label="选择卡片滑动动作"
                value={cardSwipeAction}
                onChange={(e) => updateSettings({ cardSwipeAction: e.target.value as CardSwipeAction })}
                className="min-h-11 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)]"
              >
                {CARD_SWIPE_TRAINING_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        {/* 合成文章演练台 */}
        <EdgeSwipePracticeCard onVerdict={pushEntry} />
        {cardSwipeAction !== 'none' && (
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]" data-n351-card-hint="">
            卡片滑动动作当前为「{SWIPE_ACTION_LABELS[cardSwipeAction] ?? cardSwipeAction}」——
            在文章列表的卡片上练习（同一调度器）；本演练台的侧滑只对应返回手势。
          </p>
        )}

        {/* 台账 */}
        <section
          aria-label="训练台账"
          data-testid="n351-training-ledger"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2.5"
        >
          <h3 className="text-sm font-medium text-[var(--lumi-text-tertiary)]">
            训练台账（{ledger.length}）
          </h3>
          {ledger.length === 0 ? (
            <p aria-live="polite" className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              还没有动作。在上方合成文章左缘向右滑试试。
            </p>
          ) : (
            <ul aria-live="polite" className="mt-1 flex flex-col gap-0.5">
              {ledger.map((entry) => (
                <li key={entry.id} data-n351-training-log={entry.text} className="text-xs text-[var(--lumi-text-primary)]">
                  {entry.text}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <Button variant="secondary" className="min-h-11" onClick={onClose}>
        退出训练
      </Button>
    </Dialog>
  )
}

/** 设置页入口（通用 → 手势；紧邻既有触控练习区）。 */
export function ReadingGestureTraining() {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium leading-tight text-[var(--lumi-text-primary)]">
          阅读手势训练
        </p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          在合成文章上演练侧滑返回与卡片滑动，并选择启用哪些手势；
          练习不改真实内容。
        </p>
      </div>
      <Button
        variant="secondary"
        size="sm"
        className="min-h-11 shrink-0"
        data-testid="n351-open-training"
        onClick={() => setOpen(true)}
      >
        打开训练
      </Button>
      {open && <ReadingGestureTrainingOverlay onClose={() => setOpen(false)} />}
    </div>
  )
}

export default ReadingGestureTraining
