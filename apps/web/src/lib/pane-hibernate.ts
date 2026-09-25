/** pane-hibernate — N107 工作区预览/对读窗格休眠。
 *
 * 预览窗格与对读双栏携带重型文章正文（DOMPurify 渲染后的整棵内容树）。
 * 空闲超过阈值（默认 10 分钟）后休眠：真实卸载正文 DOM（不是隐藏），
 * 仅在内存保留元数据 + 滚动位置；窗格重新获得焦点/交互时唤醒并恢复
 * 滚动位置。休眠是真实的 DOM 释放——休眠后容器内节点数显著下降，
 * 唤醒后恢复（负向断言证明不是只换图标）。
 *
 * 纯逻辑与 React 钩子分离：状态机可独立测试（计时器注入）。 */

import { useCallback, useEffect, useRef, useState } from 'react'

/** 默认空闲阈值：10 分钟。 */
export const PANE_HIBERNATE_IDLE_MS = 10 * 60 * 1000

/** 状态机判定：纯函数（测试直接覆盖）。 */
export function shouldHibernate(
  lastActiveAt: number,
  now: number,
  idleMs: number,
): boolean {
  return lastActiveAt > 0 && now - lastActiveAt >= idleMs
}

/** 窗格活动事件（被动监听，绝不阻塞滚动/输入）。 */
export const PANE_ACTIVITY_EVENTS = [
  'pointerdown',
  'keydown',
  'focusin',
  'scroll',
  'input',
] as const

export interface PaneHibernateOptions {
  /** 空闲阈值（测试注入小值）。默认 PANE_HIBERNATE_IDLE_MS。 */
  idleMs?: number
  /** 休眠/唤醒回调（埋点预留；测试观测用）。 */
  onHibernate?: () => void
  onWake?: () => void
}

export interface PaneHibernateApi {
  hibernated: boolean
  /** 绑定到滚动容器（或任意交互容器）的 ref。 */
  containerRef: React.RefObject<HTMLDivElement | null>
  /** 手动休眠/唤醒（休眠占位符上的「唤醒」按钮用）。 */
  hibernate: () => void
  wake: () => void
}

export function usePaneHibernate(
  options: PaneHibernateOptions = {},
): PaneHibernateApi {
  const idleMs = options.idleMs ?? PANE_HIBERNATE_IDLE_MS
  const [hibernated, setHibernated] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const lastActiveRef = useRef<number>(Date.now())
  const scrollPosRef = useRef<number>(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const armTimer = useCallback(() => {
    clearTimer()
    timerRef.current = setTimeout(() => {
      if (shouldHibernate(lastActiveRef.current, Date.now(), idleMs)) {
        setHibernated((prev) => {
          if (!prev && containerRef.current !== null) {
            scrollPosRef.current = containerRef.current.scrollTop
            options.onHibernate?.()
          }
          return true
        })
      }
    }, idleMs)
    // 计时器只用于测试与真实空闲；组件卸载统一清理。
  }, [clearTimer, idleMs, options])

  const wake = useCallback(() => {
    setHibernated((prev) => {
      if (prev) {
        lastActiveRef.current = Date.now()
        options.onWake?.()
        // 内容重挂载后恢复滚动位置（下一帧 DOM 就绪时执行）。
        requestAnimationFrame(() => {
          if (containerRef.current !== null) {
            containerRef.current.scrollTop = scrollPosRef.current
          }
        })
      }
      return false
    })
    armTimer()
  }, [armTimer, options])

  const hibernate = useCallback(() => {
    setHibernated((prev) => {
      if (!prev && containerRef.current !== null) {
        scrollPosRef.current = containerRef.current.scrollTop
        options.onHibernate?.()
      }
      return true
    })
    clearTimer()
  }, [clearTimer, options])

  useEffect(() => {
    if (hibernated) return
    armTimer()
    const container = containerRef.current
    const onActivity = () => {
      lastActiveRef.current = Date.now()
      armTimer()
    }
    if (container !== null) {
      for (const event of PANE_ACTIVITY_EVENTS) {
        container.addEventListener(event, onActivity, { passive: true })
      }
    }
    return () => {
      clearTimer()
      if (container !== null) {
        for (const event of PANE_ACTIVITY_EVENTS) {
          container.removeEventListener(event, onActivity)
        }
      }
    }
  }, [armTimer, clearTimer, hibernated])

  return { hibernated, containerRef, hibernate, wake }
}
