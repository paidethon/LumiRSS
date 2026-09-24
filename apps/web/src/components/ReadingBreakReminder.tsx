/** ReadingBreakReminder — F063 连续阅读护眼提醒（自包含组件）。
 *
 * 设备本计时（不上传、无服务端状态）：Reader 打开并可见时向「本次
 * 连续阅读截止点」走一个 setTimeout（间隔 = readerBreakReminderMinutes，
 * 0 = 关）。到点弹出**非阻塞**提示 chip（不抢焦点、不锁滚动）：
 * - 「知道了」进入下一轮（cycle + 1 重新计时）；
 * - 页面隐藏（后台/锁屏）即清除定时器、恢复可见重新计满——隐藏的
 *   时间就是休息，宁少勿多；
 * - 到点后定时器即终止（提示挂起等待用户确认），不自我续期。
 * 单一定时器、无轮询：不与页内任何「跑完所有计时器」的测试/逻辑
 * （runAllTimersAsync）互相拖垮。跨文章不重置（「连续阅读」语义跨篇
 * 成立），Reader 卸载即终止。 */

import { useEffect, useState } from 'react'
import { Button } from './ui/Button'

export interface ReadingBreakReminderProps {
  /** 提醒间隔（分钟）；0 = 关闭。 */
  minutes: number
}

export function ReadingBreakReminder({ minutes }: ReadingBreakReminderProps) {
  const [due, setDue] = useState(false)
  /** 「知道了」轮次：确认后 +1 重新计时（换 key 重排定时器）。 */
  const [cycle, setCycle] = useState(0)

  useEffect(() => {
    if (minutes <= 0) {
      setDue(false)
      return
    }
    setDue(false)
    let timer: number
    /** 本轮是否已到点提示（提示后不再因 visibility 重排定时器）。 */
    let fired = false
    const arm = () => {
      timer = window.setTimeout(() => {
        fired = true
        setDue(true)
      }, minutes * 60_000)
    }
    // 隐藏期间不累计连续阅读时长（隐藏 = 休息）；恢复可见重新计满。
    // （到点后 timer 已终止；提示挂起等待用户确认，不自我续期。）
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        window.clearTimeout(timer)
      } else if (!fired) {
        arm()
      }
    }
    arm()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [minutes, cycle])

  if (minutes <= 0 || !due) return null

  return (
    <div
      role="status"
      data-lumi-break-reminder=""
      className="fixed bottom-6 left-4 z-40 flex max-w-xs items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-3 py-2 shadow-[var(--lumi-shadow-popover)]"
    >
      <span className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        已连续阅读 {minutes} 分钟，休息一下眼睛吧。
      </span>
      <Button
        variant="secondary"
        size="sm"
        className="min-h-11"
        onClick={() => setCycle((c) => c + 1)}
      >
        知道了
      </Button>
    </div>
  )
}

export default ReadingBreakReminder
