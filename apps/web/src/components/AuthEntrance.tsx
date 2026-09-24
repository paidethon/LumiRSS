/** AuthEntrance — 未登录入口（0067 + P0）：按顶层路由分流。
 *
 * /activate（邀请激活，token 在 ?token=）→ ActivateScreen；
 * /register（公开注册，P0-02；实例策略关闭由服务端 403 诚实呈现）
 *   → RegisterScreen；
 * 其余 → LoginScreen。注册/激活页都是非常规入口，懒加载（不占首屏
 * 预算；Suspense 瞬时 null 无感，与 main.tsx 的 lazy 契约一致）。
 * 独立成文件还让 main.tsx 保持单一组件（fast refresh 友好）。
 */

import { Suspense, lazy } from 'react'
import LoginScreen from './LoginScreen'
import { readAppRoute } from '../lib/app-route'

const ActivateScreen = lazy(() => import('./ActivateScreen'))
const RegisterScreen = lazy(() => import('./RegisterScreen'))

export default function AuthEntrance() {
  const route = readAppRoute()
  if (route === 'activate') {
    return (
      <Suspense fallback={null}>
        <ActivateScreen />
      </Suspense>
    )
  }
  if (route === 'register') {
    return (
      <Suspense fallback={null}>
        <RegisterScreen />
      </Suspense>
    )
  }
  return <LoginScreen />
}
