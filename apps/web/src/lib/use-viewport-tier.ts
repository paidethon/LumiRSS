/** useViewportTier — P03 平板布局层的统一视口分层判定。
 *
 * 三档（与 Playwright iPad 项目断点一致）：
 *   compact <768px         —— 手机 shell（MobileHeader / TabBar / Drawer）
 *   tablet  768–1023.99px  —— 平板 shell（常驻侧栏 + Timeline/Reader 双栏）
 *   desktop ≥1024px        —— 桌面三栏（既有 CSS lg: 布局，不改 Tailwind 断点）
 *
 * 单一实现：两条 matchMedia 查询（<768 / ≥1024）+ useSyncExternalStore，
 * 订阅在首个订阅者出现时挂载、最后一个退订时移除；getSnapshot 每次实时
 * 计算（返回原始值，React 按 Object.is 比较即可，无需缓存）。SSR / jsdom
 * （无 matchMedia）默认 'compact'——与既有 useIsMobile「无 matchMedia
 * 视为移动端」约定一致，测试环境行为不变。 */

import { useSyncExternalStore } from 'react'

export type ViewportTier = 'compact' | 'tablet' | 'desktop'

// 47.99rem = 767.84px（<768，与原 App/use-is-mobile 的 mq 一致）；
// 64rem = 1024px（Tailwind lg 断点）；52.125rem = 834px（平板竖排上限：
// iPad 768/834 竖屏 → 折叠 rail + Reader 覆盖列表；>834 横排 → 双栏）。
const COMPACT_QUERY = '(max-width: 47.99rem)'
const DESKTOP_QUERY = '(min-width: 64rem)'
const TABLET_PORTRAIT_QUERY = '(max-width: 52.125rem)'

function safeMatchMedia(query: string): { matches: boolean; listen: (cb: () => void) => () => void } | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  let mql: MediaQueryList
  try {
    mql = window.matchMedia(query)
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

function computeTier(): ViewportTier {
  const compact = safeMatchMedia(COMPACT_QUERY)
  if (!compact) return 'compact'
  if (compact.matches) return 'compact'
  const desktop = safeMatchMedia(DESKTOP_QUERY)
  if (!desktop) return 'compact'
  return desktop.matches ? 'desktop' : 'tablet'
}

function subscribe(onStoreChange: () => void): () => void {
  const unlistens = [COMPACT_QUERY, DESKTOP_QUERY].map((query) => {
    const mq = safeMatchMedia(query)
    return mq ? mq.listen(onStoreChange) : () => {}
  })
  return () => {
    for (const unlisten of unlistens) unlisten()
  }
}

/** 当前视口档位。jsdom / SSR 默认 'compact'（移动端回退语义不变）。 */
export function useViewportTier(): ViewportTier {
  return useSyncExternalStore(subscribe, computeTier, () => 'compact')
}

function computeTabletPortrait(): boolean {
  const portrait = safeMatchMedia(TABLET_PORTRAIT_QUERY)
  return portrait ? portrait.matches : true
}

function subscribeTabletPortrait(onStoreChange: () => void): () => void {
  const mq = safeMatchMedia(TABLET_PORTRAIT_QUERY)
  return mq ? mq.listen(onStoreChange) : () => {}
}

/** 平板竖排（tier === tablet 且视口 ≤834px）。非 tablet 档恒 false——
 * 竖排默认（折叠 rail / Reader 覆盖列表）只属于平板层。 */
export function useTabletPortrait(): boolean {
  const tier = useViewportTier()
  const portrait = useSyncExternalStore(subscribeTabletPortrait, computeTabletPortrait, () => true)
  return tier === 'tablet' && portrait
}
