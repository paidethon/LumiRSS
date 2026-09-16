import { describe, expect, it } from 'vitest'
import { staleState } from '../lib/stale-label'

describe('staleState — 差异化失效状态（pool #13）', () => {
  it('永久失效与暂时不可用使用不同文案', () => {
    expect(staleState('not_found').badge).toBe('内容已删除')
    expect(staleState('unsupported').badge).toBe('来源暂不支持')
    expect(staleState('timeout').badge).toBe('暂时不可用')
    expect(staleState('error').badge).toBe('暂时不可用')
  })

  it('timeout/error 可重试，not_found/unsupported 不可重试', () => {
    expect(staleState('timeout').retryable).toBe(true)
    expect(staleState('error').retryable).toBe(true)
    expect(staleState('not_found').retryable).toBe(false)
    expect(staleState('unsupported').retryable).toBe(false)
  })

  it('未知/缺失原因回退通用「源已失效」', () => {
    expect(staleState(null).badge).toBe('源已失效')
    expect(staleState(undefined).badge).toBe('源已失效')
    expect(staleState('something-new').badge).toBe('源已失效')
  })
})
