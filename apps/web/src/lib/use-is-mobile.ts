/** useIsMobile — Tailwind max-md（md = 48rem / 768px）媒体判定。
 *
 * 用于「portal 化的浮层壳不能靠 CSS 切换挂载」的场景（Base UI Dialog/
 * Drawer portal 到 body，逃逸祖先的 max-md:hidden，必须在 JS 层决定
 * 渲染哪个响应式壳）。jsdom 无 matchMedia：回退 true（视为移动端，
 * 保持测试环境可渲染——与主题模块的防御一致）。 */

import { useEffect, useState } from 'react'

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
    return window.matchMedia('(max-width: 47.99rem)').matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(max-width: 47.99rem)')
    const onChange = () => setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
