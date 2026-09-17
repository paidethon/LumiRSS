/** UndoSnackbar — F20 撤销条（App 级单实例）。
 *
 * 行内操作（标记已读/收藏/移出稍后读）成功后弹出 8 秒撤销窗口；
 * 点「撤销」先做状态核对（action.check）再执行逆操作，核对失败如实
 * 提示「状态已变化」。倒计时结束自动消失；不阻塞任何交互。 */

import { useEffect, useRef, useState } from 'react'

import { useUndo } from '../store/undo'
import { Button } from './ui/Button'

export default function UndoSnackbar() {
  const current = useUndo((s) => s.current)
  const clear = useUndo((s) => s.clear)
  const expire = useUndo((s) => s.expire)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    if (current === null) return
    setConflict(false)
    const interval = window.setInterval(() => {
      expire()
      if (useUndo.getState().current === null) window.clearInterval(interval)
    }, 1000)
    timerRef.current = interval
    return () => window.clearInterval(interval)
  }, [current, expire])

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
      data-undo-snackbar
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
