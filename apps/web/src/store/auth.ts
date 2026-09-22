/** 会话认证门控 store（LUMIRSS_AUTH_MODE=session 时生效）。
 *
 * 状态机：'checking'（启动探测中）→ 'authenticated' | 'unauthenticated'。
 * basic 模式（探测返回 mode=basic）永远 authenticated —— 认证由
 * 代理层 Basic Auth 负责，Web 不建第二套登录 UI。
 *
 * 任何 API 响应 401 + type=session_required 都会翻到 unauthenticated
 * （见 api/client.ts 的 rawRequest）；登录成功翻回。离线/网络故障
 * 不翻状态 —— 「连不上」不等于「未登录」，避免误导（Phase O 离线
 * 契约）。
 *
 * 0067 多账户：identity 携带服务端核实的身份（GET /auth/session 返回，
 * 绝不取自请求体/客户端声明）——账号菜单与管理台入口按它渲染；后端
 * 才是权限真源，前端徽标只做入口可见性。
 */

import { create } from 'zustand'

export type AuthGateStatus = 'checking' | 'authenticated' | 'unauthenticated'

/** 服务端核实的身份（role 语义：owner=运营者 / admin=管理员 / member=成员）。 */
export interface AuthIdentity {
  userId: string
  username: string
  role: 'owner' | 'admin' | 'member'
}

interface AuthState {
  status: AuthGateStatus
  /** 本次会话探测到的服务端认证模式；null = 尚未探测。 */
  mode: 'basic' | 'session' | null
  /** 当前登录身份（session 模式多账户）；null = basic 模式或未探测到。 */
  identity: AuthIdentity | null
  setStatus: (status: AuthGateStatus) => void
  setMode: (mode: 'basic' | 'session' | null) => void
  setIdentity: (identity: AuthIdentity | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'checking',
  mode: null,
  identity: null,
  setStatus: (status) => set({ status }),
  setMode: (mode) => set({ mode }),
  setIdentity: (identity) => set({ identity }),
}))

/** rawRequest 在 401 session_required 时调用（幂等）。翻到未登录时
 * 一并清掉身份——旧身份残留会让账号菜单在登录页背后渲染幽灵数据。 */
export function sessionExpired(): void {
  const { status, mode } = useAuthStore.getState()
  if (mode === 'session' && status === 'authenticated') {
    useAuthStore.getState().setStatus('unauthenticated')
    useAuthStore.getState().setIdentity(null)
  }
}

/** 把 /auth/session 的身份字段归一为 AuthIdentity（字段缺失 → null）。
 * login/activate 端点只回 authenticated+expiresAt，身份由随后的
 * session 探测补齐，因此对「部分字段缺失」保持宽容；参数取 unknown
 * ——generated schema 的 AuthStatus 尚未收录 userId/username/role，
 * 避免结构重叠误报（schema 再生成后无需改动本函数）。 */
export function identityFromSession(probe: unknown): AuthIdentity | null {
  if (typeof probe !== 'object' || probe === null) return null
  const { userId, username, role } = probe as Record<string, unknown>
  if (
    typeof userId !== 'string' ||
    userId === '' ||
    typeof username !== 'string' ||
    username === '' ||
    (role !== 'owner' && role !== 'admin' && role !== 'member')
  ) {
    return null
  }
  return { userId, username, role }
}
