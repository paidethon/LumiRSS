/** ReadingRuler — R05 阅读行辅助线 + N054 增强（自包含组件）。
 *
 * 集成约定：Reader.tsx 归集成方接线，本组件**自包含**——优先
 * containerRef，否则自行 querySelector('.lumi-reader-article')；容器未
 * 就绪时观察 document.body 再挂载。
 *
 * 行为：
 * - 开关状态存 localStorage `lumirss-reading-ruler`（'1' = 开），
 *   **默认关**；宽度/深浅同样设备本地持久化（独立键，见下）；
 * - 开启后在正文上渲染一条水平辅助线：2px 半透明 accent 横线 + 上下
 *   8px 渐隐遮罩，跟随鼠标/触摸 Y 移动（pointermove，rAF 节流），
 *   离开正文容器自动隐藏；
 * - N054 宽度三档（窄 60% / 中 80% / 宽 100%）与深浅三档（1–3 级
 *   不透明度）持久化；
 * - N054 键盘操作（仅开启时）：↑/↓ 逐行移动（按正文字号×行距步进，
 *   未显示时从视口中部出现）、`[`/`]` 调宽度、`-`/`=` 调深浅、
 *   Esc 关闭；指针跟随不受影响；
 * - 纯覆盖层：fixed portal + pointer-events:none，**不改正文 DOM**
 *   （选择/复制内容零影响）；
 * - 开关按钮自带，浮于正文右上角（fixed），44px 触控目标。
 */

import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

export const READING_RULER_STORAGE_KEY = 'lumirss-reading-ruler'
/** N054：宽度三档（窄/中/宽 → 视口宽度百分比）。 */
export const READING_RULER_WIDTH_KEY = 'lumirss-reading-ruler-width'
/** N054：深浅三档（1 浅 / 2 中 / 3 深）。 */
export const READING_RULER_SHADE_KEY = 'lumirss-reading-ruler-shade'

export type RulerWidth = 'narrow' | 'medium' | 'wide'
export type RulerShade = 1 | 2 | 3

const RULER_WIDTH_VALUES: readonly RulerWidth[] = ['narrow', 'medium', 'wide']
const RULER_WIDTH_RATIO: Record<RulerWidth, number> = { narrow: 0.6, medium: 0.8, wide: 1 }
const RULER_WIDTH_LABEL: Record<RulerWidth, string> = { narrow: '窄', medium: '中', wide: '宽' }
/** 深浅档 → [主线不透明度, 渐隐不透明度]。 */
const RULER_SHADE_OPACITY: Record<RulerShade, [number, number]> = {
  1: [0.35, 0.18],
  2: [0.55, 0.28],
  3: [0.8, 0.45],
}
const RULER_SHADE_LABEL: Record<RulerShade, string> = { 1: '浅', 2: '中', 3: '深' }

function readEnum<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return allowed.includes(raw as T) ? (raw as T) : fallback
  } catch {
    return fallback
  }
}

function writeValue(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // localStorage 不可用：设置退化为会话内状态
  }
}

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
  writeValue(READING_RULER_STORAGE_KEY, enabled ? '1' : '0')
}

/** N054：读取宽度档（缺省/损坏 = 中）。 */
export function readRulerWidth(): RulerWidth {
  return readEnum(READING_RULER_WIDTH_KEY, RULER_WIDTH_VALUES, 'medium')
}

/** N054：读取深浅档（缺省/损坏 = 中）。 */
export function readRulerShade(): RulerShade {
  try {
    const raw = Number.parseInt(localStorage.getItem(READING_RULER_SHADE_KEY) ?? '', 10)
    if (raw === 1 || raw === 2 || raw === 3) return raw
  } catch {
    /* fallthrough */
  }
  return 2
}

/** 逐行步进：正文字号 × 行距（容器实测优先，CSS 变量回退，最终 28px）。
 * 真实浏览器命中 computed line-height；jsdom 走 fontSize × 变量。 */
export function rulerLineStep(container: HTMLElement | null): number {
  let fontSize = Number.NaN
  let lineHeightPx = Number.NaN
  try {
    const cs = window.getComputedStyle(container ?? document.body)
    fontSize = Number.parseFloat(cs.fontSize)
    if (cs.lineHeight.endsWith('px')) lineHeightPx = Number.parseFloat(cs.lineHeight)
  } catch {
    /* fallthrough */
  }
  if (Number.isFinite(lineHeightPx) && lineHeightPx > 0) return lineHeightPx
  let ratio = Number.NaN
  try {
    ratio = Number.parseFloat(
      document.documentElement.style.getPropertyValue('--lumi-reader-line-height'),
    )
  } catch {
    /* fallthrough */
  }
  if (Number.isFinite(fontSize) && fontSize > 0) {
    return fontSize * (Number.isFinite(ratio) && ratio > 0 ? ratio : 1.75)
  }
  return 28
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

/** 键盘操作时跳过文本输入目标（查找框/表单里打字不调辅助线）。 */
function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  return (
    target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]') !== null
  )
}

export function ReadingRuler({ containerRef }: ReadingRulerProps) {
  const [enabled, setEnabled] = useState(readRulerEnabled)
  /** 指针 Y（viewport 坐标）；null = 隐藏（未进入/已离开正文） */
  const [y, setY] = useState<number | null>(null)
  const [width, setWidth] = useState<RulerWidth>(readRulerWidth)
  const [shade, setShade] = useState<RulerShade>(readRulerShade)
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

  const changeWidth = useCallback((next: RulerWidth) => {
    setWidth(next)
    writeValue(READING_RULER_WIDTH_KEY, next)
  }, [])

  const changeShade = useCallback((next: RulerShade) => {
    setShade(next)
    writeValue(READING_RULER_SHADE_KEY, String(next))
  }, [])

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

  // ---- N054：键盘操作（开启时；↑/↓ 逐行，[/] 宽度，-/= 深浅，Esc 关） ----
  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
      if (isTextEntryTarget(event.target)) return
      const moveBy = (delta: number) => {
        setY((current) => {
          const base =
            current ??
            (typeof window !== 'undefined' && Number.isFinite(window.innerHeight)
              ? window.innerHeight / 2
              : 300)
          const max =
            typeof window !== 'undefined' && Number.isFinite(window.innerHeight)
              ? window.innerHeight
              : Number.MAX_SAFE_INTEGER
          return Math.min(max, Math.max(0, base + delta))
        })
      }
      switch (event.key) {
        case 'ArrowUp':
          event.preventDefault()
          moveBy(-rulerLineStep(container))
          break
        case 'ArrowDown':
          event.preventDefault()
          moveBy(rulerLineStep(container))
          break
        case '[':
          changeWidth(width === 'wide' ? 'medium' : 'narrow')
          break
        case ']':
          changeWidth(width === 'narrow' ? 'medium' : 'wide')
          break
        case '-':
          changeShade(Math.max(1, shade - 1) as RulerShade)
          break
        case '=':
          changeShade(Math.min(3, shade + 1) as RulerShade)
          break
        case 'Escape':
          setEnabled(false)
          writeRulerEnabled(false)
          setY(null)
          break
        default:
          return
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, container, width, shade, changeWidth, changeShade])

  const [lineOpacity, fadeOpacity] = RULER_SHADE_OPACITY[shade]
  const widthRatio = RULER_WIDTH_RATIO[width]

  return (
    <>
      {/* 辅助线覆盖层：fixed 随 viewport，pointer-events none 不挡选择。
          N054：宽度三档居中显示；深浅三档控制线与渐隐不透明度。 */}
      {enabled && y !== null && createPortal(
        <div
          aria-hidden="true"
          data-lumi-reading-ruler="true"
          data-lumi-reading-ruler-width={width}
          data-lumi-reading-ruler-shade={shade}
          className="pointer-events-none fixed z-40"
          style={{
            top: `${y - 9}px`,
            height: '18px',
            width: `${widthRatio * 100}%`,
            left: '50%',
            transform: 'translateX(-50%)',
          }}
        >
          {/* 上 8px 渐隐（透明 → accent） */}
          <div
            className="h-2 w-full"
            style={{
              background: 'linear-gradient(to bottom, transparent, var(--lumi-accent))',
              opacity: fadeOpacity,
            }}
          />
          {/* 2px 主线（半透明 accent） */}
          <div
            className="h-0.5 w-full"
            style={{ backgroundColor: 'var(--lumi-accent)', opacity: lineOpacity }}
          />
          {/* 下 8px 渐隐（accent → 透明） */}
          <div
            className="h-2 w-full"
            style={{
              background: 'linear-gradient(to top, transparent, var(--lumi-accent))',
              opacity: fadeOpacity,
            }}
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
            className="max-w-48 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1 text-right text-[11px] leading-relaxed text-[var(--lumi-text-secondary)] shadow-md"
          >
            跟随指针辅助逐行阅读（{RULER_WIDTH_LABEL[width]} · 深
            {RULER_SHADE_LABEL[shade]}）；↑↓ 逐行移动，[ ] 调宽度，- =
            调深浅，Esc 关闭。仅本设备生效（默认关）。
          </p>
        )}
      </div>
    </>
  )
}

export default ReadingRuler
