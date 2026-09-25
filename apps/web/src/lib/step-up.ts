/** step-up — N009 管理员临时提权（Web 侧）。
 *
 * 敏感管理操作（角色变更 / 暂停·恢复成员 / 配额设置 / 成员密码重置）
 * 服务端要求 X-Lumi-Step-Up 令牌（403 step_up_required 提示）。本模块：
 * - 持有本会话最近一次铸造的一次性令牌（内存级；单次使用后即失效，
 *   消费点在 client.ts 的请求发出处——发出即清除）；
 * - 提供 isStepUpRequiredError 判定（ApiError.type ===
 *   'step_up_required'），供管理台弹出密码对话框；
 * - mintAdminStepUp 走 client.ts 的铸造端点，成功后缓存令牌。
 */

import { ApiError, mintAdminStepUpToken } from '../api/client'

const STEP_UP_HEADER = 'X-Lumi-Step-Up'

/** 内存级令牌（刷新即失；单次使用语义由服务端强制，客户端发出即清）。 */
let currentToken: string | null = null

export function getStepUpToken(): string | null {
  return currentToken
}

/** 请求发出前取头并消费（单次使用：发出即清，绝不复用）。 */
export function takeStepUpHeaders(): Record<string, string> {
  if (currentToken === null) return {}
  const headers = { [STEP_UP_HEADER]: currentToken }
  currentToken = null
  return headers
}

export function isStepUpRequiredError(error: unknown): boolean {
  return error instanceof ApiError && error.type === 'step_up_required'
}

/** 用管理员自己的密码铸造一次性令牌（5 分钟有效；失败抛 ApiError）。 */
export async function mintAdminStepUp(password: string): Promise<void> {
  const result = await mintAdminStepUpToken(password)
  currentToken = result.token
}

/** step_up_required 事件（管理台监听并弹出密码对话框）。 */
const STEP_UP_EVENT = 'lumirss:step-up-required'

export function notifyStepUpRequired(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(STEP_UP_EVENT))
}

export function onStepUpRequired(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(STEP_UP_EVENT, handler)
  return () => window.removeEventListener(STEP_UP_EVENT, handler)
}
