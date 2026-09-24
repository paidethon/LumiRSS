/** N048 连续阅读间隔 —— 设备本地设置（归一化/持久化）。 */

import { beforeEach, describe, expect, it } from 'vitest'
import {
  loadReadingQueueInterval,
  normalizeReadingQueueInterval,
  READING_QUEUE_INTERVAL_OPTIONS,
  saveReadingQueueInterval,
} from '../lib/reading-queue-interval'

describe('N048 连续阅读间隔（设备本地）', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('集合内取值归一化；越界回退到关(0)', () => {
    expect(normalizeReadingQueueInterval(30)).toBe(30)
    expect(normalizeReadingQueueInterval(0)).toBe(0)
    expect(normalizeReadingQueueInterval('15')).toBe(0)
    expect(normalizeReadingQueueInterval(42)).toBe(0)
    expect(normalizeReadingQueueInterval(null)).toBe(0)
    expect(READING_QUEUE_INTERVAL_OPTIONS).toEqual([0, 15, 30, 60])
  })

  it('持久化到 localStorage；无存储环境回退关(0)', () => {
    saveReadingQueueInterval(60)
    expect(localStorage.getItem('lumirss-reading-queue-interval')).toBe('60')
    expect(loadReadingQueueInterval()).toBe(60)

    // 损坏的存储值 → 关(0)。
    localStorage.setItem('lumirss-reading-queue-interval', 'bogus')
    expect(loadReadingQueueInterval()).toBe(0)

    // 显式注入 null 存储（隐私模式）→ 读 0、写不抛。
    expect(loadReadingQueueInterval(null)).toBe(0)
    expect(() => saveReadingQueueInterval(15, null)).not.toThrow()
  })

  it('默认（无存储值）= 关(0) —— 恢复直接切换', () => {
    expect(loadReadingQueueInterval()).toBe(0)
  })

  it('存储抛异常时写操作静默降级', () => {
    const throwing = { getItem: () => null, setItem: () => { throw new Error('quota') } } as unknown as Storage
    expect(() => saveReadingQueueInterval(15, throwing)).not.toThrow()
  })

  it('getItem 抛异常时读操作回退关(0)', () => {
    const throwing = { getItem: () => { throw new Error('blocked') }, setItem: () => {} } as unknown as Storage
    expect(loadReadingQueueInterval(throwing)).toBe(0)
  })
})
