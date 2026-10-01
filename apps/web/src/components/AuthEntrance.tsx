/** AuthEntrance — 未登录入口（0067 + P0 + R01）：按顶层路由分流。
 *
 * /activate（邀请激活，token 在 ?token=）→ ActivateScreen；
 * /register（公开注册，P0-02；实例策略关闭由服务端 403 诚实呈现）
 *   → RegisterScreen；
 * 其余 → LoginScreen。注册/激活页都是非常规入口，懒加载（不占首屏
 * 预算；Suspense 瞬时 null 无感，与 main.tsx 的 lazy 契约一致）。
 * 独立成文件还让 main.tsx 保持单一组件（fast refresh 友好）。
 *
 * R01：路由必须用 useAppRoute()（订阅 pushState/ROUTE_CHANGE_EVENT），
 * 不能用一次性的 readAppRoute()——本组件挂在 AuthGate（只随认证状态
 * 重渲染）之下，登录页上的「注册 / 激活」链接靠程序化导航切换页面；
 * 一次性读取会让 URL 变了而屏幕不动（历史缺陷，登录页入口点了无反应）。
 */

import { Suspense, lazy } from 'react'
import LoginScreen from './LoginScreen'
import { useAppRoute } from '../lib/app-route'

const ActivateScreen = lazy(() => import('./ActivateScreen'))
const RegisterScreen = lazy(() => import('./RegisterScreen'))

export default function AuthEntrance() {
  const route = useAppRoute()
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
