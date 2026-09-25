/** GesturePracticeSettings — N067 触控操作练习区（设置 → 通用 → 手势）。
 *
 * 手势重映射（cardSwipeAction）是肌肉记忆：练错会真的标已读/收藏。
 * 练习区提供 3 张示例卡片，复用**同一份**手势调度器（lib/card-swipe 的
 * swipeStartAllowed / swipeIsVertical / swipePreviewOffset /
 * swipeShouldCommit / swipePreviewOpacity——与 EntryCard/EntryRow 完全
 * 相同的函数），并附长按 / 双击练习；所有动作只写入面板内可见的练习
 * 台账（如「触发:标为已读(练习)」），绝不发起任何真实变更/API 调用；
 * 退出后一切还原（无持久状态）。
 *
 * 动作标签取自当前 settings.cardSwipeAction——练习的就是用户配置的动作。
 * 浮层用 ui/Dialog 原语（Base UI 承担焦点陷阱 / Escape / 滚动锁）。 */

import { useRef, useState } from 'react'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'
import { useAppSettings } from '../store/app-settings'
import {
  SWIPE_ACTION_LABELS,
  swipeIsVertical,
  swipePreviewOffset,
  swipePreviewOpacity,
  swipeShouldCommit,
  swipeStartAllowed,
} from '../lib/card-swipe'

/** 长按判定时长（ms；与移动端长按菜单惯值一致）。 */
export const PRACTICE_LONG_PRESS_MS = 600
/** 双击判定间隔（ms）。 */
export const PRACTICE_DOUBLE_TAP_MS = 300
/** 台账容量（防练习刷屏）。 */
export const PRACTICE_LEDGER_CAP = 20

export interface PracticeLedgerEntry {
  id: number
  text: string
}

let practiceEntrySeq = 0

function nextLedgerId(): number {
  practiceEntrySeq += 1
  return practiceEntrySeq
}

/** 单张练习卡片：同一手势调度器 + 本地台账回调（无任何 mutation）。 */
function PracticeCard({
  index,
  actionLabel,
  swipeEnabled,
  onAction,
}: {
  index: number
  actionLabel: string
  swipeEnabled: boolean
  onAction: (text: string) => void
}) {
  const [swipeDx, setSwipeDx] = useState(0)
  const touchStartRef = useRef<{
    x: number
    y: number
    /** 滑动提交允许（启用动作 + 非左缘）。 */
    tracking: boolean
    /** 长按/双击练习允许（非左缘即可）。 */
    tappable: boolean
  } | null>(null)
  const longPressTimerRef = useRef<number | null>(null)
  const longPressFiredRef = useRef(false)
  const lastTapRef = useRef<number>(0)

  const clearLongPress = () => {
    if (longPressTimerRef.current !== null) {
      window.clearTimeout(longPressTimerRef.current)
      longPressTimerRef.current = null
    }
  }

  const onTouchStart = (event: React.TouchEvent) => {
    const touch = event.touches[0]
    if (!touch) return
    longPressFiredRef.current = false
    const edgeOk = swipeStartAllowed(touch.clientX)
    touchStartRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      // 滑动提交还需要启用动作（cardSwipeAction !== 'none'）
      tracking: swipeEnabled && edgeOk,
      // 长按 / 双击练习与动作开关无关，但左缘 24px 让位照常生效
      tappable: edgeOk,
    }
    // 长按练习（与滑动独立；一旦触发，本次触摸不再计滑动提交）
    clearLongPress()
    longPressTimerRef.current = window.setTimeout(() => {
      longPressTimerRef.current = null
      longPressFiredRef.current = true
      touchStartRef.current = null
      setSwipeDx(0)
      onAction('触发:长按(练习)')
    }, PRACTICE_LONG_PRESS_MS)
  }

  const onTouchMove = (event: React.TouchEvent) => {
    const start = touchStartRef.current
    if (start === null) return
    const touch = event.touches[0]
    if (!touch) return
    const dx = touch.clientX - start.x
    const dy = touch.clientY - start.y
    if (swipeIsVertical(dx, dy)) {
      // 纵向让出（滚动意图）：取消长按与水平预览
      clearLongPress()
      setSwipeDx(0)
      return
    }
    setSwipeDx(swipePreviewOffset(dx))
  }

  const onTouchEnd = (event: React.TouchEvent) => {
    const start = touchStartRef.current
    touchStartRef.current = null
    clearLongPress()
    setSwipeDx(0)
    if (start === null || longPressFiredRef.current) return
    const touch = event.changedTouches[0]
    const dx = touch !== undefined ? touch.clientX - start.x : 0
    const dy = touch !== undefined ? touch.clientY - start.y : 0
    // 同一调度器语义：非纵向且 |dx| ≥ 80 → 提交（练习 = 只记账）
    if (start.tracking && swipeShouldCommit(dx, dy)) {
      onAction(`触发:${actionLabel}(练习)`)
      return
    }
    // 双击练习（轻点两次；左缘起点让给返回手势，不计）
    if (!start.tappable) return
    const now = Date.now()
    if (now - lastTapRef.current <= PRACTICE_DOUBLE_TAP_MS) {
      lastTapRef.current = 0
      onAction('触发:双击(练习)')
      return
    }
    lastTapRef.current = now
  }

  const onTouchCancel = () => {
    touchStartRef.current = null
    clearLongPress()
    setSwipeDx(0)
  }

  return (
    <div className="relative overflow-hidden rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]">
      {/* 动作背景层（与 EntryCard 同一预览形态：跟手侧 + 不透明度） */}
      {swipeEnabled && swipeDx !== 0 && (
        <div
          aria-hidden="true"
          data-swipe-action-hint={actionLabel}
          className={cx(
            'pointer-events-none absolute inset-y-0 flex items-center gap-1.5 bg-[var(--lumi-accent-soft)] px-5 text-xs font-medium text-[var(--lumi-accent-text)]',
            swipeDx > 0 ? 'left-0 justify-start' : 'right-0 justify-end',
          )}
          style={{ opacity: swipePreviewOpacity(swipeDx) }}
        >
          {actionLabel}
        </div>
      )}
      <div
        data-testid={`practice-card-${index}`}
        data-practice-card=""
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchCancel}
        className="relative flex min-h-24 items-center gap-3 bg-[var(--lumi-surface)] px-4 py-4"
        style={swipeDx !== 0 ? { transform: `translateX(${swipeDx}px)` } : undefined}
      >
        <span
          aria-hidden="true"
          className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[var(--lumi-surface-hover)] text-sm font-medium text-[var(--lumi-text-secondary)]"
        >
          {index}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
            练习卡片 {index}
          </p>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
            滑动（≥80px）{swipeEnabled ? `提交「${actionLabel}」` : '（当前动作：无）'}·
            长按 · 双击——都只记入台账
          </p>
        </div>
      </div>
    </div>
  )
}

/** 练习区浮层（Dialog 原语：Escape / 焦点陷阱 / 滚动锁由 Base UI 承担）。 */
export function GesturePracticeOverlay({ onClose }: { onClose: () => void }) {
  const cardSwipeAction = useAppSettings((s) => s.settings.cardSwipeAction)
  const [ledger, setLedger] = useState<PracticeLedgerEntry[]>([])
  const swipeEnabled = cardSwipeAction !== 'none'
  const actionLabel = SWIPE_ACTION_LABELS[cardSwipeAction] ?? cardSwipeAction

  const pushEntry = (text: string) => {
    setLedger((prev) => [{ id: nextLedgerId(), text }, ...prev].slice(0, PRACTICE_LEDGER_CAP))
  }

  return (
    <Dialog open onClose={onClose} title="手势练习区" panelClassName="max-w-xl">
      <div className="flex flex-col gap-3">
        <p className="text-xs leading-5 text-[var(--lumi-text-secondary)]">
          这里的卡片使用与文章列表完全相同的手势调度器（含左缘 24px 让位、
          纵向让出、80px 提交阈值）。所有动作只写入下方台账，不会改动任何
          真实数据。
        </p>
        <div className="flex flex-col gap-2">
          {[1, 2, 3].map((index) => (
            <PracticeCard
              key={index}
              index={index}
              actionLabel={actionLabel}
              swipeEnabled={swipeEnabled}
              onAction={pushEntry}
            />
          ))}
        </div>
        <section
          aria-label="练习台账"
          data-testid="practice-ledger"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2.5"
        >
          <h4 className="text-xs font-medium text-[var(--lumi-text-tertiary)]">
            练习台账（{ledger.length}）
          </h4>
          {ledger.length === 0 ? (
            <p aria-live="polite" className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              还没有动作。在上方卡片上滑动 / 长按 / 双击试试。
            </p>
          ) : (
            <ul aria-live="polite" className="mt-1 flex flex-col gap-0.5">
              {ledger.map((entry) => (
                <li key={entry.id} data-practice-log={entry.text} className="text-xs text-[var(--lumi-text-primary)]">
                  {entry.text}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <Button variant="secondary" className="min-h-11" onClick={onClose}>
        退出练习区
      </Button>
    </Dialog>
  )
}

/** 设置页入口（通用 → 手势）。 */
export function GesturePracticeSettings() {
  const [open, setOpen] = useState(false)
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium leading-none text-[var(--lumi-text-primary)]">
          触控操作练习区
        </p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          在示例卡片上安全练习滑动 / 长按 / 双击；动作只记录在练习台账，
          不会改动任何真实数据。
        </p>
      </div>
      <Button variant="secondary" size="sm" className="min-h-11 shrink-0" data-testid="open-gesture-practice" onClick={() => setOpen(true)}>
        打开练习区
      </Button>
      {open && <GesturePracticeOverlay onClose={() => setOpen(false)} />}
    </div>
  )
}

export default GesturePracticeSettings
