/** useIsMobile — 非 desktop（<1024px）媒体判定（P03 起由视口分层派生）。
 *
 * 用于「portal 化的浮层壳不能靠 CSS 切换挂载」的场景（Base UI Dialog/
 * Drawer portal 到 body，逃逸祖先的 max-lg:hidden，必须在 JS 层决定
 * 渲染哪个响应式壳）。
 *
 * P03：断点从 max-md（<768）提升为「非 desktop 档」（<1024）——平板
 * （768–1023）同样触摸优先：Sheet/全屏设置壳/移动工具栏布局延伸到整个
 * <1024 区间；此前 <768 已为 true 的语义不变（compact ⊂ 非 desktop）。
 * jsdom 无 matchMedia → useViewportTier 回退 'compact' → 仍视为移动端
 * （既有测试约定不变）。 */

import { useViewportTier } from './use-viewport-tier'

export function useIsMobile(): boolean {
  return useViewportTier() !== 'desktop'
}
