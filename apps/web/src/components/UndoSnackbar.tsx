/** UndoSnackbar — F20 撤销条（App 级单实例）。
 *
 * 行内操作（标记已读/收藏/移出稍后读）成功后弹出 8 秒撤销窗口；
 * 点「撤销」先做状态核对（action.check）再执行逆操作，核对失败如实
 * 提示「状态已变化」。倒计时结束自动消失；不阻塞任何交互。
 *
 * FIX-117：悬停/聚焦暂停倒计时（可暂停读取）——指针悬停或键盘焦点
 * 进入条内即停表，离开后续起剩余时长；新动作 push 覆盖旧动作（单槽
 * 设计，天然不堆积）。 */

import { useEffect, useRef, useState } from 'react'

import { useUndo } from '../store/undo'
import { Button } from './ui/Button'

export default function UndoSnackbar() {
  const current = useUndo((s) => s.current)
  const clear = useUndo((s) => s.clear)
  const expire = useUndo((s) => s.expire)
  const extend = useUndo((s) => s.extend)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const timerRef = useRef<number | null>(null)
  // FIX-117：暂停时刻的剩余时长（恢复时续起）
  const pausedRemainingRef = useRef<number | null>(null)

  useEffect(() => {
    if (current === null) return
    setConflict(false)
    pausedRemainingRef.current = null
    const interval = window.setInterval(() => {
      expire()
      if (useUndo.getState().current === null) window.clearInterval(interval)
    }, 1000)
    timerRef.current = interval
    return () => window.clearInterval(interval)
  }, [current, expire])

  // FIX-117：可暂停读取——悬停/聚焦停表，离开/失焦续起剩余时长。
  const pauseCountdown = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    const state = useUndo.getState().current
    if (state !== null && pausedRemainingRef.current === null) {
      pausedRemainingRef.current = Math.max(0, state.expiresAt - Date.now())
    }
  }
  const resumeCountdown = () => {
    const remaining = pausedRemainingRef.current
    pausedRemainingRef.current = null
    if (remaining !== null && useUndo.getState().current !== null) {
      extend(remaining)
    }
    if (timerRef.current === null && useUndo.getState().current !== null) {
      timerRef.current = window.setInterval(() => {
        expire()
        if (useUndo.getState().current === null && timerRef.current !== null) {
          window.clearInterval(timerRef.current)
          timerRef.current = null
        }
      }, 1000)
    }
  }

  if (current === null) return null

  async function handleUndo() {
    if (busy || current === null) return
    setBusy(true)
    try {
      const ok = await current.check()
      if (!ok) {
        setConflict(true)
      } else {
        await current.undo()
        clear()
      }
    } catch {
      setConflict(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-20 left-1/2 z-40 -translate-x-1/2 lg:bottom-6"
      data-undo-snackbar=""
      onMouseEnter={pauseCountdown}
      onMouseLeave={resumeCountdown}
      onFocus={pauseCountdown}
      onBlur={resumeCountdown}
    >
      <div className="flex items-center gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-4 py-2.5 shadow-lg">
        {conflict ? (
          <span className="text-sm text-[var(--lumi-text-secondary)]">
            状态已变化，未执行撤销。
          </span>
        ) : (
          <>
            <span className="text-sm text-[var(--lumi-text-primary)]">{current.label}</span>
            <Button variant="primary" size="sm" disabled={busy} onClick={handleUndo}>
              {busy ? '撤销中…' : '撤销'}
            </Button>
          </>
        )}
        <Button variant="ghost" size="sm" onClick={clear}>
          {conflict ? '知道了' : '忽略'}
        </Button>
      </div>
    </div>
  )
}
