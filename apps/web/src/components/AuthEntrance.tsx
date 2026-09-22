/** AuthEntrance — 未登录入口（0067）：按顶层路由分流。
 *
 * /activate（邀请激活，token 在 ?token=）→ ActivateScreen；
 * 其余 → LoginScreen。激活页懒加载（非常规入口，不占首屏预算；
 * Suspense 瞬时 null 无感，与 main.tsx 的 lazy 契约一致）。
 * 独立成文件还让 main.tsx 保持单一组件（fast refresh 友好）。
 */

import { Suspense, lazy } from 'react'
import LoginScreen from './LoginScreen'
import { readAppRoute } from '../lib/app-route'

const ActivateScreen = lazy(() => import('./ActivateScreen'))

export default function AuthEntrance() {
  if (readAppRoute() === 'activate') {
    return (
      <Suspense fallback={null}>
        <ActivateScreen />
      </Suspense>
    )
  }
  return <LoginScreen />
}
