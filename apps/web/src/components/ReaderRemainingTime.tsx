/** ReaderRemainingTime — F075 进度条旁剩余阅读时间。
 *
 * 显示位置：进度条旁（滚动容器顶部右上，绝对定位不占布局）。剩余
 * 分钟数 = 全文估时 × (1 - 当前进度)，随滚动实时更新（rAF 节流）。
 * 速度走 lib/reading-time 的 ReadingSpeed 接口——默认速度实现；
 * timeline 域 F051 校准速度落地后由调用方传入 speed 即可，接口已留好。
 * 进度关闭或估算关闭（readerShowReadingTime）时不渲染。 */

import { useEffect, useRef, useState } from 'react'
import { estimateRemainingMinutes, type ReadingSpeed } from '../lib/reading-time'

export interface ReaderRemainingTimeProps {
  /** 取当前滚动容器（Reader ref 双挂；惰性调用，挂载后才非空）。 */
  getContainer: () => HTMLDivElement | null
  /** 全文评估输入（contentText 优先，同 ReaderHeader 阅读时间估算）。 */
  text: string
  /** 是否显示（进度条与阅读时间估算开关同时开启才显示）。 */
  enabled: boolean
  /** 可选校准速度（默认速度；F051 落地后传入实测速度）。 */
  speed?: ReadingSpeed
}

export default function ReaderRemainingTime({
  getContainer,
  text,
  enabled,
  speed,
}: ReaderRemainingTimeProps) {
  const [ratio, setRatio] = useState(0)
  /** 帧令牌（非挂起句柄）：rAF 同步执行（测试 stub）时回调先于赋值
   * 运行，句柄判空会永久卡死节流——与 ReadingRuler 同一教训。 */
  const generationRef = useRef(0)

  useEffect(() => {
    if (!enabled) return
    const container = getContainer()
    if (container === null) return

    const update = () => {
      const node = getContainer()
      if (node === null) return
      const max = node.scrollHeight - node.clientHeight
      const top = node.scrollTop
      setRatio(max > 0 && top > 0 ? Math.min(1, top / max) : 0)
    }
    // rAF 节流：滚动事件高频，进度写入每帧最多一次（首帧经 rAF 求值，
    // 不在 effect 体内同步 setState）。
    const scheduleUpdate = () => {
      const token = ++generationRef.current
      requestAnimationFrame(() => {
        if (token === generationRef.current) update()
      })
    }
    const onScroll = () => scheduleUpdate()
    container.addEventListener('scroll', onScroll, { passive: true })
    scheduleUpdate()
    return () => {
      generationRef.current += 1 // 使未决帧失效
      container.removeEventListener('scroll', onScroll)
    }
  }, [enabled, getContainer])

  if (!enabled || ratio <= 0) return null
  const minutes = estimateRemainingMinutes({ text, ratio, speed })

  return (
    <div
      data-lumi-remaining-time=""
      aria-hidden="true"
      className="pointer-events-none absolute right-3 top-2 z-20 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-2 py-0.5 text-[11px] tabular-nums text-[var(--lumi-text-secondary)] shadow-[var(--lumi-shadow-popover)]"
    >
      {minutes <= 0 ? '即将读完' : `剩余约 ${minutes} 分钟`}
    </div>
  )
}
