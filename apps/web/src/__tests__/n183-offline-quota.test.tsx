/** N183 —— 离线资料设备配额（lib + 组件）。
 *
 * mock caches：用量统计；清理预览按「大 → 小」且尊重配额；应用只删
 * 缓存条目且绝不发起任何网络 fetch/DELETE 调用（服务器收藏/笔记
 * 完全不受影响）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  applyCleanup,
  enumerateCacheEntries,
  planCleanup,
  readQuotaMb,
  writeQuotaMb,
} from '../lib/offline-quota'
import { OfflineQuotaSection } from '../components/settings/OfflineQuotaSection'

interface FakeEntry {
  url: string
  body: string
  date?: string
  opaque?: boolean
  /** size：直接声明 blob 大小（鸭子类型响应，避免真实 60MB 字符串） */
  size?: number
}

interface FakeCaches {
  caches: {
    keys: () => Promise<string[]>
    open: (name: string) => Promise<{
      keys: () => Promise<Request[]>
      match: (request: Request) => Promise<Response | undefined>
      delete: (request: Request) => Promise<boolean>
    }>
  }
  deleted: string[]
}

function makeCaches(entries: FakeEntry[]): FakeCaches {
  const store = new Map<string, FakeEntry>()
  for (const entry of entries) store.set(entry.url, entry)
  const deleted: string[] = []
  const cache = {
    keys: async () => [...store.keys()].map((url) => new Request(url)),
    match: async (request: Request) => {
      const entry = store.get(request.url)
      if (!entry) return undefined
      const date = entry.date ?? new Date().toUTCString()
      if (entry.size !== undefined) {
        return {
          type: 'default',
          headers: { get: () => date },
          blob: async () => ({ size: entry.size }),
        } as unknown as Response
      }
      if (entry.opaque) {
        // 不透明响应（跨域无 CORS 头）：type=opaque、blob 不可读——
        // 用鸭子类型模拟（undici 的 Response 无法构造 status 0）。
        return {
          type: 'opaque',
          headers: { get: () => date },
          blob: async () => ({ size: 0 }),
        } as unknown as Response
      }
      return new Response(entry.body, { status: 200, headers: new Headers({ date }) })
    },
    delete: async (request: Request) => {
      if (!store.has(request.url)) return false
      store.delete(request.url)
      deleted.push(request.url)
      return true
    },
  }
  return {
    caches: {
      keys: async () => ['lumirss-offline'],
      open: async () => cache,
    },
    deleted,
  }
}

describe('N183 离线配额（lib）', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('用量统计：已知字节与未知大小分开（opaque 不冒充 0）', async () => {
    const { caches } = makeCaches([
      { url: 'https://a.example/1', body: 'x'.repeat(100) },
      { url: 'https://a.example/2', body: '', opaque: true },
    ])
    vi.stubGlobal('caches', caches)
    const usage = await enumerateCacheEntries()
    expect(usage.available).toBe(true)
    expect(usage.entryCount).toBe(2)
    expect(usage.unknownSizeCount).toBe(1)
    expect(usage.knownBytes).toBe(100)
  })

  it('清理预览尊重配额：按大 → 小只挑必要的条目（小条目保留）', async () => {
    const { caches } = makeCaches([
      { url: 'https://a/big', body: 'x'.repeat(120), date: 'Mon, 02 Feb 2026 00:00:00 GMT' },
      { url: 'https://a/mid', body: 'x'.repeat(80), date: 'Mon, 02 Feb 2026 00:00:00 GMT' },
      { url: 'https://a/small', body: 'x'.repeat(10), date: 'Mon, 02 Feb 2026 00:00:00 GMT' },
    ])
    vi.stubGlobal('caches', caches)
    const usage = await enumerateCacheEntries()
    expect(usage.knownBytes).toBe(210)
    const plan = planCleanup(usage, 150)
    expect(plan.overQuota).toBe(true)
    // 超 60 字节：先删最大的 120 → 已足够，mid/small 保留
    expect(plan.candidates.map((candidate) => candidate.url)).toEqual(['https://a/big'])
    expect(plan.reclaimableBytes).toBe(120)
  })

  it('未超配额 → overQuota=false，无候选', async () => {
    const { caches } = makeCaches([{ url: 'https://a/tiny', body: 'x'.repeat(10) }])
    vi.stubGlobal('caches', caches)
    const usage = await enumerateCacheEntries()
    const plan = planCleanup(usage, 200 * 1024 * 1024)
    expect(plan.overQuota).toBe(false)
    expect(plan.candidates).toEqual([])
  })

  it('应用清理只删除缓存条目，绝不调用 fetch（无删除 API 调用）', async () => {
    const fake = makeCaches([
      { url: 'https://a/keep', body: 'x'.repeat(10) },
      { url: 'https://a/drop', body: 'x'.repeat(200) },
    ])
    vi.stubGlobal('caches', fake.caches)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const deletedCount = await applyCleanup([
      { cacheName: 'lumirss-offline', url: 'https://a/drop', sizeBytes: 200 },
    ])
    expect(deletedCount).toBe(1)
    expect(fake.deleted).toEqual(['https://a/drop'])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('配额偏好保存在本设备（默认 200；越界收敛）', () => {
    expect(readQuotaMb()).toBe(200)
    writeQuotaMb(500)
    expect(readQuotaMb()).toBe(500)
    writeQuotaMb(99_999)
    expect(readQuotaMb()).toBe(2048)
    writeQuotaMb(1)
    expect(readQuotaMb()).toBe(50)
  })
})

describe('N183 离线配额（组件）', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('统计显示用量与清理候选；应用后展示结果；全程无 fetch 调用', async () => {
    // 配额调到最小 50MB，缓存 60MB → 超额 10MB，出现清理候选
    localStorage.setItem('lumirss-offline-quota-mb', '50')
    const fake = makeCaches([
      { url: 'https://a/big', body: '', size: 60 * 1024 * 1024 },
    ])
    vi.stubGlobal('caches', fake.caches)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<OfflineQuotaSection />)

    fireEvent.click(screen.getByRole('button', { name: '统计本设备离线缓存' }))
    await waitFor(() => {
      expect(document.querySelector('[data-quota-usage]')?.textContent).toContain('已用')
    })
    expect(document.querySelector('[data-quota-usage]')?.textContent).toContain('60.0 MB')
    expect(document.querySelector('[data-quota-usage]')?.textContent).toContain('50 MB')

    await waitFor(() => {
      expect(document.querySelector('[data-quota-candidates]')?.textContent).toContain('https://a/big')
    })
    fireEvent.click(screen.getByRole('button', { name: /清理 1 条/ }))
    await waitFor(
      () => {
        expect(document.querySelector('[data-quota-result]')?.textContent).toContain('已清理 1 条')
      },
      { timeout: 8000 },
    )
    expect(fake.deleted).toEqual(['https://a/big'])
    // 关键负向断言：应用阶段没有发出任何网络请求（无删除 API）
    expect(fetchMock).not.toHaveBeenCalled()
  }, 15000)
})
