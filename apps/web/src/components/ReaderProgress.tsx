/** ReaderProgress — F11 阅读进度条。
 *
 * readerShowReadingProgress=true 时，在 Reader 滚动容器顶部渲染 3px
 * 细进度条（--lumi-accent），百分比 = scrollTop / (scrollHeight -
 * clientHeight)。原生 passive scroll 监听 + rAF 节流；无滚动空间或
 * 进度为 0 时隐藏（不占布局，绝对定位）。
 *
 * 已知取舍（诚实）：AI/笔记面板在同一滚动容器内，会计入总高度——
 * 进度对「整个滚动容器」计算，符合任务定义。 */

import { useEffect, useRef, useState } from 'react'

export interface ReaderProgressProps {
  /** 取当前滚动容器（Reader ref 双挂；惰性调用，挂载后才非空）。 */
  getContainer: () => HTMLDivElement | null
  /** 设置开关（readerShowReadingProgress）。 */
  enabled: boolean
}

export default function ReaderProgress({ getContainer, enabled }: ReaderProgressProps) {
  const [ratio, setRatio] = useState(0)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) {
      setRatio(0)
      return
    }
    const container = getContainer()
    if (container === null) return

    const update = () => {
      rafRef.current = null
      const node = getContainer()
      if (node === null) {
        setRatio(0)
        return
      }
      const max = node.scrollHeight - node.clientHeight
      const top = node.scrollTop
      setRatio(max > 0 && top > 0 ? Math.min(1, top / max) : 0)
    }
    // rAF 节流：滚动事件高频，进度写入每帧最多一次。
    const onScroll = () => {
      if (rafRef.current !== null) return
      rafRef.current = requestAnimationFrame(update)
    }
    container.addEventListener('scroll', onScroll, { passive: true })
    update()
    return () => {
      container.removeEventListener('scroll', onScroll)
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [enabled, getContainer])

  if (!enabled || ratio <= 0) return null

  return (
    <div
      aria-hidden="true"
      data-lumi-progress=""
      className="pointer-events-none absolute inset-x-0 top-0 z-20 h-[3px]"
    >
      <div
        data-lumi-progress-bar=""
        className="h-full"
        style={{ width: `${Math.round(ratio * 10000) / 100}%`, backgroundColor: 'var(--lumi-accent)' }}
      />
    </div>
  )
}
