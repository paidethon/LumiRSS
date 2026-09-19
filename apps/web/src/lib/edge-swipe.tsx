/** P1.3（2026-09 移动端专项）：移动端左缘侧滑返回 — 渐进增强。
 *
 * 设计值（本项目自定，非 Apple 官方标准；真机表现待验证）：
 * - 起点：距左缘 ≤ 20px 的单指 touchstart；
 * - 意图：横向位移 > 12px 且 |dx| > |dy|*1.5 才进入预览（否则放弃，
 *   绝不抢占纵向滚动/文字选择/图片平移/卡片滑动）；
 * - 提交：位移 ≥ 96px 或整体速度 ≥ 0.5 px/ms；
 * - 预览：main 跟手 translateX（dx*0.35，上限 120px）；不足阈值回弹。
 *
 * 边界与共存：
 * - 不全局 preventDefault、不改全局 touch-action —— 只在横向意图成立
 *   后对当前手势 preventDefault；
 * - iOS Safari 原生边缘返回若先接管（touchcancel / 手势中 popstate），
 *   本手势立即放弃并跳过自身提交（防双跳）；PWA 内由本手势补足；
 * - 减少动态效果：跳过跟手预览动画，手势判定与提交仍可用；
 * - 根页面（无应用内可返回页）不执行 back。
 */

import { useEffect, useRef } from 'react'
import { canGoBack, goBack } from './nav-history'

export const EDGE_SWIPE_START_PX = 20
export const EDGE_SWIPE_INTENT_PX = 12
export const EDGE_SWIPE_COMMIT_PX = 96
export const EDGE_SWIPE_COMMIT_VELOCITY = 0.5 // px/ms
export const EDGE_SWIPE_PREVIEW_MAX_PX = 120

/** 手势状态机（纯数据；单测直接驱动判定函数即可）。 */
interface SwipeState {
  candidate: boolean
  previewing: boolean
  nativeTookOver: boolean
  startX: number
  startY: number
  lastX: number
  startT: number
}

function newSwipeState(): SwipeState {
  return {
    candidate: false,
    previewing: false,
    nativeTookOver: false,
    startX: 0,
    startY: 0,
    lastX: 0,
    startT: 0,
  }
}

/** touchstart 判定：是否进入候选（左缘）。 */
export function swipeStartCandidate(x: number): boolean {
  return x <= EDGE_SWIPE_START_PX
}

/** touchmove 判定：横向意图成立才激活预览。 */
export function swipeIntentMet(dx: number, dy: number): boolean {
  return dx > EDGE_SWIPE_INTENT_PX && Math.abs(dx) > Math.abs(dy) * 1.5
}

/** touchend 判定：位移或速度达到阈值即提交返回。 */
export function swipeShouldCommit(dx: number, elapsedMs: number): boolean {
  if (dx >= EDGE_SWIPE_COMMIT_PX) return true
  if (elapsedMs <= 0) return false
  return dx / elapsedMs >= EDGE_SWIPE_COMMIT_VELOCITY
}

/** 预览位移（跟手弱化 + 上限）。 */
export function previewOffset(dx: number): number {
  return Math.min(EDGE_SWIPE_PREVIEW_MAX_PX, Math.max(0, dx) * 0.35)
}

const SPRING_TRANSITION = 'transform 160ms cubic-bezier(0.2, 0.8, 0.2, 1)'

/** EdgeSwipeBack — 挂载后接管 document 左缘手势；disabled（减少动态
 * 效果）时跳过跟手预览动画，判定与提交仍可用。 */
export function EdgeSwipeBack({ disabled = false }: { disabled?: boolean }) {
  const stateRef = useRef<SwipeState>(newSwipeState())

  useEffect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return

    const content = () => document.querySelector('main')

    const resetPreview = () => {
      const el = content()
      if (el instanceof HTMLElement) {
        el.style.transition = SPRING_TRANSITION
        el.style.transform = ''
        delete el.dataset.swiping
      }
    }

    const onStart = (event: TouchEvent) => {
      const state = stateRef.current
      state.candidate = false
      state.previewing = false
      state.nativeTookOver = false
      if (event.touches.length !== 1) return
      const touch = event.touches[0]!
      if (!swipeStartCandidate(touch.clientX)) return
      state.candidate = true
      state.startX = touch.clientX
      state.startY = touch.clientY
      state.lastX = touch.clientX
      state.startT = performance.now()
    }

    const onMove = (event: TouchEvent) => {
      const state = stateRef.current
      if (!state.candidate || state.nativeTookOver) return
      const touch = event.touches[0]
      if (touch === undefined) return
      const dx = touch.clientX - state.startX
      const dy = touch.clientY - state.startY
      if (!state.previewing) {
        if (!swipeIntentMet(dx, dy)) {
          // 明显纵向意图（或回退到边缘内）→ 让出，不再评估本次手势。
          if (Math.abs(dy) > 24) state.candidate = false
          return
        }
        state.previewing = true
      }
      // 横向意图已成立：本手势不再是滚动，可安全拦截。
      event.preventDefault()
      state.lastX = touch.clientX
      const el = content()
      if (el instanceof HTMLElement && !disabled) {
        el.dataset.swiping = '1'
        el.style.transition = 'none'
        el.style.transform = `translateX(${previewOffset(dx)}px)`
      }
    }

    const onFinish = (_event: TouchEvent) => {
      const state = stateRef.current
      const wasPreviewing = state.previewing
      const dx = state.lastX - state.startX
      const elapsedMs = Math.max(1, performance.now() - state.startT)
      const shouldCommit =
        wasPreviewing && !state.nativeTookOver && swipeShouldCommit(dx, elapsedMs)
      state.candidate = false
      state.previewing = false
      resetPreview()
      if (shouldCommit && canGoBack()) goBack()
    }

    const onCancel = () => {
      // iOS 原生边缘返回接管（touchcancel）→ 放弃本次手势，绝不双跳。
      stateRef.current.nativeTookOver = true
      stateRef.current.candidate = false
      stateRef.current.previewing = false
      resetPreview()
    }

    const onPopState = () => {
      // 手势进行中浏览器自己完成了返回 → 放弃提交。
      stateRef.current.nativeTookOver = true
    }

    document.addEventListener('touchstart', onStart, { passive: true })
    document.addEventListener('touchmove', onMove, { passive: false })
    document.addEventListener('touchend', onFinish, { passive: true })
    document.addEventListener('touchcancel', onCancel, { passive: true })
    window.addEventListener('popstate', onPopState)
    return () => {
      document.removeEventListener('touchstart', onStart)
      document.removeEventListener('touchmove', onMove)
      document.removeEventListener('touchend', onFinish)
      document.removeEventListener('touchcancel', onCancel)
      window.removeEventListener('popstate', onPopState)
    }
  }, [disabled])

  return null
}
