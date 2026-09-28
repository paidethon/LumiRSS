// FIX-218 Web 侧适配——step-up 作用域透传的模块级契约。
// 服务端契约（FIX-218 BFF 批）：铸造必须声明 (operation, targetUserId)，
// 消费按作用域逐字匹配；403 step_up_required 错误体携带该作用域，
// 经 ApiError.extra → notifyStepUpRequired → 铸造参数 透传到本模块。
import { afterEach, describe, expect, it, vi } from 'vitest'

const mintMock = vi.hoisted(() => vi.fn())
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    readonly status: number
    readonly type: string
    constructor(status: number, type: string, message?: string) {
      super(message ?? type)
      this.status = status
      this.type = type
    }
  },
  mintAdminStepUpToken: mintMock,
}))

import {
  isStepUpRequiredError,
  mintAdminStepUp,
  notifyStepUpRequired,
  onStepUpRequired,
} from '../lib/step-up'

describe('step-up scoped mint (FIX-218 web side)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('mint forwards the 403-declared operation and targetUserId verbatim', async () => {
    mintMock.mockResolvedValue({ token: 't', expiresInMinutes: 5, header: 'X-Lumi-Step-Up' })
    await mintAdminStepUp('pw', { operation: 'user_role_change', targetUserId: 'u3' })
    expect(mintMock).toHaveBeenCalledWith('pw', 'user_role_change', 'u3')
  })

  it('absent scope omits both fields so the server rejects with a typed message', async () => {
    mintMock.mockRejectedValue(new Error('422'))
    await expect(
      mintAdminStepUp('pw', { operation: null, targetUserId: null }),
    ).rejects.toThrow('422')
    expect(mintMock).toHaveBeenCalledWith('pw', null, null)
  })

  it('notify/onStepUpRequired carries the scope through the window event', () => {
    const seen: Array<{ operation: string | null; targetUserId: string | null } | undefined> = []
    const off = onStepUpRequired((scope) => seen.push(scope))
    notifyStepUpRequired({ operation: 'user_quota_set', targetUserId: 'u7' })
    off()
    notifyStepUpRequired({ operation: 'x', targetUserId: null })
    expect(seen[0]).toEqual({ operation: 'user_quota_set', targetUserId: 'u7' })
    expect(seen[1]).toBeUndefined()
  })

  it('isStepUpRequiredError keys on the stable error type', async () => {
    const { ApiError } = await import('../api/client')
    expect(isStepUpRequiredError(new ApiError(403, 'step_up_required', '需要提权'))).toBe(true)
    expect(isStepUpRequiredError(new ApiError(403, 'forbidden', '拒绝'))).toBe(false)
    expect(isStepUpRequiredError(new Error('plain'))).toBe(false)
  })
})
