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
 */

import { create } from 'zustand'

export type AuthGateStatus = 'checking' | 'authenticated' | 'unauthenticated'

interface AuthState {
  status: AuthGateStatus
  /** 本次会话探测到的服务端认证模式；null = 尚未探测。 */
  mode: 'basic' | 'session' | null
  setStatus: (status: AuthGateStatus) => void
  setMode: (mode: 'basic' | 'session' | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'checking',
  mode: null,
  setStatus: (status) => set({ status }),
  setMode: (mode) => set({ mode }),
}))

/** rawRequest 在 401 session_required 时调用（幂等）。 */
export function sessionExpired(): void {
  const { status, mode } = useAuthStore.getState()
  if (mode === 'session' && status === 'authenticated') {
    useAuthStore.getState().setStatus('unauthenticated')
  }
}
