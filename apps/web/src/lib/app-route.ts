/** app-route — 无 router 库的极简顶层路由（与 #/playground 同策略）。
 *
 * LumiRSS 只有两个独立顶层页面，不值得引入 router：
 * - /activate  邀请激活页（未登录可达，token 从 ?token= 读）；
 * - /admin     管理台（登录后可达；权限以后端 403 为准）。
 * 其余一切仍是 App 内的 section/view 状态。
 *
 * 路由源 = location.pathname 或 hash（`#/admin` 形式供静态托管/禁用
 * history API 的环境兜底，与 dev playground 判定一致）。导航用
 * history.pushState + 自定义事件通知订阅者；useAppRoute 以
 * useSyncExternalStore 订阅（popstate 同步浏览器返回键）。
 */

import { useSyncExternalStore } from 'react'

export type AppRoute = 'app' | 'activate' | 'admin'

const ROUTE_CHANGE_EVENT = 'lumirss-route-change'

/** 从 hash 里取出路径部分（`#/admin?x=1` → `/admin`）；无 hash 返回 null。 */
function hashPath(): string | null {
  const hash = window.location.hash
  if (!hash.startsWith('#/')) return null
  return hash.slice(1)
}

/** 当前顶层路由。pathname 与 hash 双源（hash 优先——pushState 后两者
 * 一致；静态托管只支持 hash 时也能工作）。 */
export function readAppRoute(): AppRoute {
  if (typeof window === 'undefined') return 'app'
  const path = hashPath() ?? window.location.pathname
  if (path === '/activate' || path.startsWith('/activate/')) return 'activate'
  if (path === '/admin' || path.startsWith('/admin/')) return 'admin'
  return 'app'
}

/** 程序化导航（pushState + 通知）。replace=true 时用 replaceState
 * （激活成功回应用等不应留在历史里）。pushState 以完整 URL 为目标，
 * 旧 hash 自动被覆盖。 */
export function navigateAppRoute(route: AppRoute, replace = false): void {
  if (typeof window === 'undefined') return
  const target = route === 'app' ? '/' : `/${route}`
  try {
    if (replace) window.history.replaceState(null, '', target)
    else window.history.pushState(null, '', target)
  } catch {
    // history 不可用（极端嵌入环境）：忽略，事件仍会让订阅者按新路由渲染
  }
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT))
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange)
  window.addEventListener(ROUTE_CHANGE_EVENT, onChange)
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(ROUTE_CHANGE_EVENT, onChange)
  }
}

/** React 订阅：路由变化（程序化 / 浏览器返回键）触发重渲染。 */
export function useAppRoute(): AppRoute {
  return useSyncExternalStore(subscribe, readAppRoute, () => 'app' as AppRoute)
}

/** 激活链接里的 token：优先 `?token=`（location.search）；hash 路由形式
 * `#/activate?token=...` 同样解析。找不到返回 null。 */
export function readActivateToken(): string | null {
  if (typeof window === 'undefined') return null
  const sources: string[] = [window.location.search]
  const hash = window.location.hash
  if (hash.startsWith('#/activate')) {
    const queryIndex = hash.indexOf('?')
    if (queryIndex !== -1) sources.push(hash.slice(queryIndex))
  }
  for (const source of sources) {
    const token = new URLSearchParams(source).get('token')
    if (token !== null && token !== '') return token
  }
  return null
}
