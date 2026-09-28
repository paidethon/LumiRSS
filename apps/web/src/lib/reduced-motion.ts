/** reduced-motion — 减少动效偏好的统一判定（FIX-112）。
 *
 * 两个真源必须等效生效（tokens.css 的全局 0.01ms 兜底只覆盖 CSS，
 * JS 驱动的平滑滚动/跟手预览动画需要在这里显式判定）：
 * - OS 偏好：`prefers-reduced-motion: reduce`（matchMedia，可订阅变化）；
 * - 应用内偏好：`<html data-motion-reduce="true">`（app-settings.reduceMotion
 *   经 applyAppearance 挂载，与 CSS 消费端同一属性）。
 *
 * `scrollBehavior()` 统一所有 JS 侧 `behavior: 'smooth'` 的取值：
 * 减少动效 → 'auto'（瞬时定位），否则 'smooth'。fix-112 守卫测试
 * 断言全库不允许裸写 `'smooth'` 字面量——必须经此函数。
 */

import { useSyncExternalStore } from 'react'

/** OS 偏好：prefers-reduced-motion: reduce（jsdom/SSR 无 matchMedia → false）。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** 应用内偏好：<html data-motion-reduce="true">（applyAppearance 挂载）。 */
export function appReduceMotion(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.dataset.motionReduce === 'true'
}

/** 任一偏好成立即减少动效（应用内开关与 OS 偏好等效）。 */
export function shouldReduceMotion(): boolean {
  return appReduceMotion() || prefersReducedMotion()
}

/** JS 侧平滑滚动的 behavior 取值：减少动效 → 'auto'（瞬时跳转）。 */
export function scrollBehavior(): 'auto' | 'smooth' {
  return shouldReduceMotion() ? 'auto' : 'smooth'
}

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function safeMatchMedia(): { matches: boolean; listen: (cb: () => void) => () => void } | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  let mql: MediaQueryList
  try {
    mql = window.matchMedia(REDUCED_MOTION_QUERY)
  } catch {
    return null
  }
  return {
    matches: mql.matches,
    listen: (cb) => {
      if (typeof mql.addEventListener !== 'function') return () => {}
      mql.addEventListener('change', cb)
      return () => mql.removeEventListener('change', cb)
    },
  }
}

function subscribe(onStoreChange: () => void): () => void {
  const mq = safeMatchMedia()
  return mq ? mq.listen(onStoreChange) : () => {}
}

/** 响应式版本：OS 偏好变化即时重渲染；jsdom/SSR 默认 false。
 * 应用内偏好（dataset）非 observable，随消费方自身的设置驱动渲染更新。 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false)
}
