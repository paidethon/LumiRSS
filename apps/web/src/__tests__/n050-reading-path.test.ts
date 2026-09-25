/** E1: N050 个人阅读路径记录 —— 设备本地边界（负向契约）+ 行为。

- 序列记录：打开顺序保留；30 分钟无活动 → 新会话（旧序列保留）；
- restore：面板「恢复」从最近一条开始按原顺序回放；
- clear / disable：清空与停用（停用后 record 为 no-op）；
- **设备本地硬边界**：所有路径操作零网络调用（fetch 断言），且
  client.ts（API 层）不 import reading-path ——服务端没有承载端点。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearReadingPath,
  getReadingPath,
  isReadingPathEnabled,
  READING_PATH_MAX_ENTRIES,
  recordReadingPathEntry,
  setReadingPathEnabled,
} from '../lib/reading-path'

beforeEach(() => {
  window.localStorage.clear()
  clearReadingPath()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('N050 reading path (device-local)', () => {
  it('records opened entries in order', () => {
    const now = Date.now()
    expect(recordReadingPathEntry('rss:a', '甲', now)).toBe(true)
    expect(recordReadingPathEntry('rss:b', '乙', now + 1000)).toBe(true)
    expect(recordReadingPathEntry('rss:c', null, now + 2000)).toBe(true)
    const state = getReadingPath()
    expect(state.entries.map((entry) => entry.ref)).toEqual(['rss:a', 'rss:b', 'rss:c'])
  })

  it('starts a new session after 30 minutes of inactivity (old series kept)', () => {
    const now = Date.now()
    recordReadingPathEntry('rss:a', null, now)
    recordReadingPathEntry('rss:b', null, now + 60_000)
    // 31 分钟后 → 新会话（a/b 保留，c 垫后）。
    const later = now + 31 * 60 * 1000
    expect(recordReadingPathEntry('rss:c', null, later)).toBe(true)
    const refs = getReadingPath().entries.map((entry) => entry.ref)
    expect(refs).toEqual(['rss:a', 'rss:b', 'rss:c'])
    // 同一条目连续重复打开（同会话内）不重复记录。
    expect(recordReadingPathEntry('rss:c', null, later + 1000)).toBe(false)
    expect(getReadingPath().entries.length).toBe(3)
  })

  it('clears and disables (record becomes a no-op)', () => {
    recordReadingPathEntry('rss:a', null)
    clearReadingPath()
    expect(getReadingPath().entries).toEqual([])

    setReadingPathEnabled(false)
    expect(isReadingPathEnabled()).toBe(false)
    expect(recordReadingPathEntry('rss:b', null)).toBe(false)
    expect(getReadingPath().entries).toEqual([])

    setReadingPathEnabled(true)
    expect(recordReadingPathEntry('rss:b', null)).toBe(true)
  })

  it('stays bounded at the cap', () => {
    const now = Date.now()
    for (let i = 0; i < READING_PATH_MAX_ENTRIES + 10; i += 1) {
      recordReadingPathEntry(`rss:${i}`, null, now + i * 1000)
    }
    expect(getReadingPath().entries.length).toBe(READING_PATH_MAX_ENTRIES)
  })

  it('makes ZERO network calls for every operation (device-local hard boundary)', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const xhrSpy = vi.spyOn(globalThis, 'XMLHttpRequest', 'get')
    recordReadingPathEntry('rss:a', '甲')
    recordReadingPathEntry('rss:b', '乙')
    getReadingPath()
    clearReadingPath()
    setReadingPathEnabled(false)
    setReadingPathEnabled(true)
    isReadingPathEnabled()
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(xhrSpy).not.toHaveBeenCalled()
  })

  it('is never imported by the API layer (client.ts) and no API path carries it', async () => {
    // 静态边界：client.ts 不 import reading-path（防止未来有人把本地
    // 序列发到服务端）；生成契约里没有任何 reading-path 端点。
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const clientSource = readFileSync(
      join(process.cwd(), 'src', 'api', 'client.ts'),
      'utf8',
    )
    expect(clientSource.includes('reading-path')).toBe(false)
    const generated = readFileSync(
      join(process.cwd(), 'src', 'api', 'generated', 'schema.ts'),
      'utf8',
    )
    expect(generated.toLowerCase().includes('readingpath')).toBe(false)
    expect(generated.toLowerCase().includes('reading-path')).toBe(false)
  })
})
