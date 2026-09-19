/** ArticleLightbox — F14 图片灯箱 / F16 表格展开面板共用的全屏浮层。
 *
 * 图片模式（images 非空）：遮罩 + 图片 contain 居中，滚轮/双指缩放
 * （1–4x）、拖拽平移、←/→ 切换正文图片、Esc/遮罩点击/× 关闭；打开时
 * 焦点入容器（tabIndex=-1 + focus），焦点归还由调用方负责（关闭后
 * focus 回触发图片）。
 *
 * 内容模式（children）：同一遮罩承载任意面板（表格展开：横向可滚、
 * 保留语义 table/th/td）。不使用 Fullscreen API。
 *
 * 关闭统一走 onClose（portal 到 body；z 用 --lumi-z-floating）。 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { cx } from './ui/cx'

export interface LightboxImage {
  src: string
  alt?: string
}

export interface ArticleLightboxProps {
  open: boolean
  onClose: () => void
  /** aria-label（dialog 名称）。 */
  label?: string
  /** 图片模式：正文图片列表（空/缺省 = 内容模式）。 */
  images?: LightboxImage[]
  startIndex?: number
  /** 内容模式（如表格展开面板）。 */
  children?: ReactNode
}

const MIN_ZOOM = 1
const MAX_ZOOM = 4

export default function ArticleLightbox({
  open,
  onClose,
  label = '图片查看',
  images,
  startIndex = 0,
  children,
}: ArticleLightboxProps) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const [index, setIndex] = useState(startIndex)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  // 拖拽/双指手势的瞬时状态（不触发渲染，move 时才写 state）。
  const gestureRef = useRef<{
    pointerId: number | null
    startX: number
    startY: number
    baseX: number
    baseY: number
  } | null>(null)
  const pinchRef = useRef<{ distance: number; baseZoom: number } | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const isImageMode = images !== undefined && images.length > 0

  // 打开：重置视图 + 焦点入灯箱；关闭后状态归零（下次打开干净）。
  useEffect(() => {
    if (!open) return
    setIndex(Math.min(Math.max(startIndex, 0), Math.max(0, (images?.length ?? 1) - 1)))
    setZoom(1)
    setOffset({ x: 0, y: 0 })
    boxRef.current?.focus()
  }, [open, startIndex, images])

  // Esc 关闭（capture：优先于页面级快捷键）；图片模式 ←/→ 切换。
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (!isImageMode || (images?.length ?? 0) < 2) return
      if (event.key === 'ArrowRight') {
        setIndex((i) => (i + 1) % images!.length)
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      } else if (event.key === 'ArrowLeft') {
        setIndex((i) => (i - 1 + images!.length) % images!.length)
        setZoom(1)
        setOffset({ x: 0, y: 0 })
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [open, isImageMode, images])

  if (!open) return null

  const resetView = () => {
    setZoom(1)
    setOffset({ x: 0, y: 0 })
  }

  // 缩放钳制 [1, 4]（不用 lib/clamp——它按整四舍五入，0.5 档会被吞掉）。
  const stepZoom = (delta: number) =>
    setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z + delta)))

  // 双指缩放：以两触点距离比缩放（简化实现，不做锚点换算——平移仍可拖）。
  const touchDistance = (touches: { length: number; [index: number]: { clientX: number; clientY: number } }): number | null =>
    touches.length === 2
      ? Math.hypot(
          touches[0]!.clientX - touches[1]!.clientX,
          touches[0]!.clientY - touches[1]!.clientY,
        )
      : null

  const image = isImageMode ? images![Math.min(index, images!.length - 1)] : null

  return createPortal(
    <div
      ref={boxRef}
      role="dialog"
      aria-modal="true"
      aria-label={label}
      tabIndex={-1}
      data-lumi-lightbox=""
      className="fixed inset-0 z-[var(--lumi-z-floating)] bg-black/85 outline-none"
      onClick={() => onCloseRef.current()}
      onWheel={(e) => {
        if (!isImageMode) return
        stepZoom(e.deltaY < 0 ? 0.25 : -0.25)
      }}
      onTouchStart={(e) => {
        if (!isImageMode) return
        const distance = touchDistance(e.touches)
        if (distance !== null) pinchRef.current = { distance, baseZoom: zoom }
      }}
      onTouchMove={(e) => {
        if (!isImageMode) return
        const pinch = pinchRef.current
        const distance = touchDistance(e.touches)
        if (pinch !== null && distance !== null && pinch.distance > 0) {
          setZoom(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, (distance / pinch.distance) * pinch.baseZoom)))
        }
      }}
      onTouchEnd={() => {
        pinchRef.current = null
      }}
    >
      {image !== null ? (
        <>
          <img
            src={image.src}
            alt={image.alt ?? ''}
            draggable={false}
            aria-label={image.alt !== '' ? image.alt : undefined}
            onClick={(e) => e.stopPropagation()}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture?.(e.pointerId)
              gestureRef.current = {
                pointerId: e.pointerId,
                startX: e.clientX,
                startY: e.clientY,
                baseX: offset.x,
                baseY: offset.y,
              }
            }}
            onPointerMove={(e) => {
              const gesture = gestureRef.current
              if (gesture === null || gesture.pointerId !== e.pointerId) return
              setOffset({
                x: gesture.baseX + (e.clientX - gesture.startX),
                y: gesture.baseY + (e.clientY - gesture.startY),
              })
            }}
            onPointerUp={() => {
              gestureRef.current = null
            }}
            onPointerCancel={() => {
              gestureRef.current = null
            }}
            className="absolute left-1/2 top-1/2 max-h-[92dvh] max-w-[92vw] cursor-grab object-contain select-none active:cursor-grabbing"
            style={{
              transform: `translate(calc(-50% + ${offset.x}px), calc(-50% + ${offset.y}px)) scale(${zoom})`,
            }}
          />
          {/* 底部控制条：缩放（1–4x）+ 多图计数；点击不关闭 */}
          <div
            className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-black/50 px-2 py-1"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              aria-label="缩小"
              onClick={() => stepZoom(-0.5)}
              className="inline-flex min-h-8 min-w-11 items-center justify-center rounded-full text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              −
            </button>
            {images!.length > 1 && (
              <span
                aria-live="polite"
                data-lumi-lightbox-counter=""
                className="min-w-12 text-center text-xs text-white tabular-nums"
              >
                {Math.min(index, images!.length - 1) + 1} / {images!.length}
              </span>
            )}
            <button
              type="button"
              aria-label="放大"
              onClick={() => stepZoom(0.5)}
              className="inline-flex min-h-8 min-w-11 items-center justify-center rounded-full text-xs text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              ＋
            </button>
          </div>
          {(images?.length ?? 0) > 1 && (
            <>
              <div className="absolute inset-y-0 left-1 flex items-center" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  aria-label="上一张"
                  onClick={() => {
                    setIndex((i) => (i - 1 + images!.length) % images!.length)
                    resetView()
                  }}
                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <ChevronLeft aria-hidden className="size-6" />
                </button>
              </div>
              <div className="absolute inset-y-0 right-1 flex items-center" onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  aria-label="下一张"
                  onClick={() => {
                    setIndex((i) => (i + 1) % images!.length)
                    resetView()
                  }}
                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  <ChevronRight aria-hidden className="size-6" />
                </button>
              </div>
            </>
          )}
        </>
      ) : (
        // 内容模式：点击面板内部不关闭（只有遮罩/×/Esc 关闭）。
        <div
          onClick={(e) => e.stopPropagation()}
          className={cx(
            'absolute inset-x-3 top-[6dvh] bottom-[6dvh] flex flex-col overflow-hidden',
            'rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)] sm:inset-x-10',
          )}
          data-lumi-lightbox-panel=""
        >
          {children}
        </div>
      )}

      <div className="absolute right-3 top-3" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          aria-label="关闭"
          onClick={() => onCloseRef.current()}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        >
          <X aria-hidden className="size-5" />
        </button>
      </div>
    </div>,
    document.body,
  )
}
