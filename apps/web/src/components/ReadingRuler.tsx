/** ReadingRuler — R05 阅读行辅助线（自包含组件）。
 *
 * 集成约定：Reader.tsx 归集成方接线，本组件**自包含**——优先
 * containerRef，否则自行 querySelector('.lumi-reader-article')；容器未
 * 就绪时观察 document.body 再挂载。
 *
 * 行为：
 * - 开关状态存 localStorage `lumirss-reading-ruler`（'1' = 开），
 *   **默认关**；
 * - 开启后在正文上渲染一条水平辅助线：2px 半透明 accent 横线 + 上下
 *   8px 渐隐遮罩，跟随鼠标/触摸 Y 移动（pointermove，rAF 节流），
 *   离开正文容器自动隐藏；
 * - 覆盖层 pointer-events:none，绝不遮挡正文选择/点击；
 * - 开关按钮自带，浮于正文右上角（fixed），44px 触控目标。
 */

import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export const READING_RULER_STORAGE_KEY = 'lumirss-reading-ruler'

/** 读取开关（缺省/损坏 = 关）。 */
export function readRulerEnabled(): boolean {
  try {
    return localStorage.getItem(READING_RULER_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

/** 写入开关（关 = 存 '0'，明确覆盖而非删 key）。 */
export function writeRulerEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(READING_RULER_STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    // localStorage 不可用：开关退化为会话内状态
  }
}

/** rAF 不可用（测试/老环境）时退化为 setTimeout，逻辑不变。 */
function scheduleFrame(fn: () => void): () => void {
  if (typeof requestAnimationFrame === 'function') {
    const handle = requestAnimationFrame(() => fn())
    return () => cancelAnimationFrame(handle)
  }
  const handle = setTimeout(fn, 16)
  return () => clearTimeout(handle)
}

export interface ReadingRulerProps {
  /** 正文容器（缺省时组件自找 .lumi-reader-article） */
  containerRef?: React.RefObject<HTMLElement | null>
}

export function ReadingRuler({ containerRef }: ReadingRulerProps) {
  const [enabled, setEnabled] = useState(readRulerEnabled)
  /** 指针 Y（viewport 坐标）；null = 隐藏（未进入/已离开正文） */
  const [y, setY] = useState<number | null>(null)
  const [container, setContainer] = useState<HTMLElement | null>(null)

  const findContainer = useCallback((): HTMLElement | null => {
    if (containerRef?.current) return containerRef.current
    return document.querySelector<HTMLElement>('.lumi-reader-article')
  }, [containerRef])

  // ---- 自包含挂载：找容器（未就绪则观察 DOM） ----
  useEffect(() => {
    let bodyObserver: MutationObserver | null = null
    const attach = (): boolean => {
      const el = findContainer()
      if (el === null) return false
      setContainer(el)
      return true
    }
    if (!attach()) {
      bodyObserver = new MutationObserver(() => {
        if (attach()) {
          bodyObserver?.disconnect()
          bodyObserver = null
        }
      })
      bodyObserver.observe(document.body, { childList: true, subtree: true })
    }
    return () => {
      bodyObserver?.disconnect()
      setContainer(null)
    }
  }, [findContainer])

  const toggle = () => {
    setEnabled((prev) => {
      writeRulerEnabled(!prev)
      return !prev
    })
    setY(null)
  }

  // ---- 指针跟随（rAF 节流；离开容器隐藏） ----
  // 用 generation token 而非「挂起句柄」判空：rAF 同步执行（测试 stub /
  // 部分环境）时回调先于赋值运行，句柄判空会永久卡死节流。
  useEffect(() => {
    if (!enabled || container === null) {
      setY(null)
      return
    }
    let scheduled = false
    let generation = 0
    const onMove = (e: PointerEvent) => {
      const clientY = e.clientY
      if (scheduled) return
      scheduled = true
      const token = ++generation
      scheduleFrame(() => {
        scheduled = false
        if (token === generation) setY(clientY)
      })
    }
    const onHide = () => {
      generation += 1
      scheduled = false
      setY(null)
    }
    container.addEventListener('pointermove', onMove)
    container.addEventListener('pointerleave', onHide)
    container.addEventListener('pointercancel', onHide)
    return () => {
      container.removeEventListener('pointermove', onMove)
      container.removeEventListener('pointerleave', onHide)
      container.removeEventListener('pointercancel', onHide)
    }
  }, [enabled, container])

  return (
    <>
      {/* 辅助线覆盖层：fixed 随 viewport，pointer-events none 不挡选择 */}
      {enabled && y !== null && createPortal(
        <div
          aria-hidden="true"
          data-lumi-reading-ruler="true"
          className="pointer-events-none fixed inset-x-0 z-40"
          style={{ top: `${y - 9}px`, height: '18px' }}
        >
          {/* 上 8px 渐隐（透明 → accent） */}
          <div
            className="h-2 w-full"
            style={{ background: 'linear-gradient(to bottom, transparent, var(--lumi-accent))', opacity: 0.28 }}
          />
          {/* 2px 主线（半透明 accent） */}
          <div className="h-0.5 w-full" style={{ backgroundColor: 'var(--lumi-accent)', opacity: 0.55 }} />
          {/* 下 8px 渐隐（accent → 透明） */}
          <div
            className="h-2 w-full"
            style={{ background: 'linear-gradient(to top, transparent, var(--lumi-accent))', opacity: 0.28 }}
          />
        </div>,
        document.body,
      )}

      {/* 开关按钮：浮于正文右上角（fixed，随 viewport 不随滚动抖动） */}
      <div className={cx('fixed right-3 top-3 z-40 flex flex-col items-end gap-1.5')}>
        <Button
          variant="secondary"
          size="sm"
          className="min-h-11 shadow-md"
          aria-pressed={enabled}
          onClick={toggle}
        >
          {enabled ? '关闭行辅助线' : '行辅助线'}
        </Button>
        {enabled && (
          <p
            role="note"
            aria-label="行辅助线说明"
            className="max-w-44 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1 text-right text-[11px] leading-relaxed text-[var(--lumi-text-secondary)] shadow-md"
          >
            跟随指针辅助逐行阅读；离开正文自动隐藏。仅本设备生效（默认关）。
          </p>
        )}
      </div>
    </>
  )
}

export default ReadingRuler
