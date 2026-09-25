/** app-route — 无 router 库的极简顶层路由（与 #/playground 同策略）。
 *
 * LumiRSS 只有三个独立顶层页面，不值得引入 router：
 * - /activate  邀请激活页（未登录可达，token 从 ?token= 读）；
 * - /register  公开注册页（未登录可达；实例策略关闭时由服务端 403）；
 * - /admin     管理台（登录后可达；权限以后端 403 为准）。
 * 其余一切仍是 App 内的 section/view 状态。
 *
 * 路由源 = location.pathname 或 hash（`#/admin` 形式供静态托管/禁用
 * history API 的环境兜底，与 dev playground 判定一致）。导航用
 * history.pushState + 自定义事件通知订阅者；useAppRoute 以
 * useSyncExternalStore 订阅（popstate 同步浏览器返回键）。
 */

import { useSyncExternalStore } from 'react'

export type AppRoute = 'app' | 'activate' | 'register' | 'admin'

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
  if (path === '/register' || path.startsWith('/register/')) return 'register'
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

/** 导航到任意同源路径（登录/注册成功后回 ?next= 目标用）。路径已经
 * isSafeAuthRedirectPath 校验；订阅者按 readAppRoute 的判定结果渲染
 * （未知路径回落 'app'，App 内部 view 不受影响）。 */
export function navigateToPath(path: string, replace = false): void {
  if (typeof window === 'undefined') return
  try {
    if (replace) window.history.replaceState(null, '', path)
    else window.history.pushState(null, '', path)
  } catch {
    // history 不可用（极端嵌入环境）：忽略，事件仍会让订阅者按新路由渲染
  }
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT))
}

/** F015 认证前目标（?next=）的同源路径校验。
 *
 * 规则（开放重定向防护的最小集合）：
 * - 非空、以单 `/` 开头（相对同源路径；`foo/bar`、空串都拒绝）；
 * - 禁止 `//` 开头（协议相对 URL `//evil.com` 会被浏览器当作
 *   `scheme://evil.com`——最经典的开放重定向载体）；
 * - 禁止任何 scheme（`http:` 等）；既然强制以 `/` 开头，这里防的是
 *   借反斜杠变体：`\` 在部分解析器里被当作 `/`，一律拒绝；
 * - 禁止控制字符与空白两端（`\n\r\t` 等可被中间层剥离后改变语义）。
 *
 * 不通过 → 返回 null，调用方回退默认页（登录后进 `/`）。 */
export function isSafeAuthRedirectPath(value: string | null): boolean {
  if (value === null || value === '') return false
  if (!value.startsWith('/')) return false
  if (value.startsWith('//')) return false
  if (value.includes('\\')) return false
  // 控制字符 / 空白两端（\n\r\t 空格等可被中间层剥离后改变语义）。
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i)
    if (code <= 0x20 || code === 0x7f) return false
  }
  return true
}

/** 读取认证后要回到的目标（F015）。`?next=` 只在 location.search 与
 * hash 路由形式（`#/?next=…`）里找；非法值一律归一为 null（回退默认页），
 * 绝不原样跳转。 */
export function readAuthRedirectTarget(): string | null {
  if (typeof window === 'undefined') return null
  const sources: string[] = [window.location.search]
  const hash = window.location.hash
  if (hash.startsWith('#/')) {
    const queryIndex = hash.indexOf('?')
    if (queryIndex !== -1) sources.push(hash.slice(queryIndex))
  }
  for (const source of sources) {
    const raw = new URLSearchParams(source).get('next')
    if (isSafeAuthRedirectPath(raw)) return raw
  }
  return null
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
