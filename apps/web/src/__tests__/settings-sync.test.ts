/** settings-sync 测试 — 0017 local-first + server-durable 同步。
 *
 * 覆盖（AD-0017-2）：
 * - hydration：server 无文档（stored=false）→ 本地值作迁移种子 PUSH；
 * - hydration：server 有文档 → server 值覆盖本地（本会话 dirty key 除外）；
 * - 串行化 debounce + 最新值必胜（17→18→19→20 只落 20）；
 * - 离线/PATCH 失败不回滚 UI（local-first 不变）；
 * - 非 portable 变更（布局/过滤规则）不产生设置 PATCH。 */

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useAppSettings, SETTINGS_STORAGE_KEY } from '../store/app-settings'
import {
  flushSettingsSyncForTests,
  initSettingsSync,
  resetSettingsSyncForTests,
} from '../store/settings-sync'
import type { ServerSettings } from '../api/types'

/** 服务端在测试里的内存态（模拟 lumi.sqlite app.settings 行）。 */
function makeServer(): {
  stored: boolean
  doc: Partial<ServerSettings>
  patchCalls: Record<string, string | number | boolean>[]
  failPatch: boolean
} {
  return { stored: false, doc: {}, patchCalls: [], failPatch: false }
}

function stubFetch(server: ReturnType<typeof makeServer>) {
  const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    const path = String(url)
    if (path === '/api/v1/settings') {
      const method = init?.method ?? 'GET'
      if (method === 'GET') {
        return new Response(
          JSON.stringify({ schemaVersion: 1, stored: server.stored, ...server.doc }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (method === 'PATCH') {
        if (server.failPatch) {
          return new Response(JSON.stringify({ error: { type: 'network', message: 'down' } }), {
            status: 502,
          })
        }
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, string | number | boolean>
        server.patchCalls.push(body)
        server.stored = true
        server.doc = { ...server.doc, ...body }
        return new Response(
          JSON.stringify({ schemaVersion: 1, stored: true, ...server.doc }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
    }
    return new Response(JSON.stringify({ error: { type: 'not_found', message: path } }), {
      status: 404,
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const flush = () => flushSettingsSyncForTests()

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  resetSettingsSyncForTests()
  useAppSettings.getState().reset()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetSettingsSyncForTests()
})

describe('hydration — 首次访问迁移种子（stored=false）', () => {
  it('server 无文档时 PUSH 本地 portable 值作为种子', async () => {
    const server = makeServer()
    stubFetch(server)
    useAppSettings.getState().update({ readerFontSize: 22, themeMode: 'dark' })

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(server.stored).toBe(true))
    await flush()

    expect(server.patchCalls.length).toBeGreaterThanOrEqual(1)
    const pushed = server.patchCalls[0]
    expect(pushed.readerFontSize).toBe(22)
    expect(pushed.themeMode).toBe('dark')
    // 种子包含全部 portable 键，且不携带任何 secret 字段
    expect(pushed.readerLineHeight).toBe(1.85)
    expect(pushed).not.toHaveProperty('apiKey')
    expect(pushed).not.toHaveProperty('filterRules')
  })
})

describe('hydration — server 有文档（stored=true）', () => {
  it('server 值覆盖本地（server-durable 优先）', async () => {
    const server = makeServer()
    server.stored = true
    server.doc = { readerFontSize: 24, themeMode: 'light', readerPageMargin: 40 }
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(24))

    const s = useAppSettings.getState().settings
    expect(s.readerFontSize).toBe(24)
    expect(s.themeMode).toBe('light')
    expect(s.readerPageMargin).toBe(40)
    // hydration 也写回本地缓存（离线启动可用）
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(24)
  })

  it('本会话用户已改的 dirty key 不被迟到的 hydration 覆盖', async () => {
    const server = makeServer()
    server.stored = true
    // 服务端值 24，但用户在 hydration 落定前已把字号拖到 20
    server.doc = { readerFontSize: 24, themeMode: 'light' }
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    // 用户立刻拖动（hydration GET 尚未返回）
    useAppSettings.getState().update({ readerFontSize: 20 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.themeMode).toBe('light'))

    const s = useAppSettings.getState().settings
    expect(s.readerFontSize).toBe(20) // 用户拖动值保住
    expect(s.themeMode).toBe('light') // 其它 server 值正常合并
  })
})

describe('串行化 + debounce — 最新值必胜', () => {
  it('快速连续拖动 17→18→19→20 后，最终 PATCH 只落 20（不产生请求洪泛）', async () => {
    const server = makeServer()
    server.stored = true
    server.doc = { readerFontSize: 17 }
    const fetchMock = stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    const patchBefore = server.patchCalls.length
    for (const size of [18, 19, 20]) {
      useAppSettings.getState().update({ readerFontSize: size })
    }
    await flush()

    // 只产生一次（或少量）PATCH；最终值必须是 20，绝不允许停在 18
    const sizePatches = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === 'PATCH',
    )
    expect(sizePatches.length).toBeLessThanOrEqual(2)
    expect(server.doc.readerFontSize).toBe(20)
    expect(useAppSettings.getState().settings.readerFontSize).toBe(20)
    expect(patchBefore).toBe(0) // hydration 阶段无多余 PATCH
  })
})

describe('离线 / 失败 — UI 不回滚', () => {
  it('PATCH 失败时本地值保持不变（无回滚、无抛出）', async () => {
    const server = makeServer()
    server.stored = true
    server.doc = { readerFontSize: 17 }
    server.failPatch = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    expect(() => useAppSettings.getState().update({ readerFontSize: 26 })).not.toThrow()
    await flush()

    // UI / 本地缓存保持 26（server 写入失败不回滚 local-first 状态）
    expect(useAppSettings.getState().settings.readerFontSize).toBe(26)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(26)
  })

  it('hydration GET 失败（离线启动）静默，本地设置照常工作', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ error: { type: 'offline' } }), { status: 0 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    expect(() => initSettingsSync({ debounceMs: 0 })).not.toThrow()
    useAppSettings.getState().update({ readerFontSize: 19 })
    await flush()
    expect(useAppSettings.getState().settings.readerFontSize).toBe(19)
  })
})

describe('portable 边界 — 非同步设置不触发设置 PATCH', () => {
  it('布局/过滤规则等 device-local 变更不写 /api/v1/settings', async () => {
    const server = makeServer()
    server.stored = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    server.patchCalls.length = 0
    useAppSettings.getState().update({ sidebarWidth: 280, timelineCollapsed: true })
    // device-local 变更不调度 flush：给 debounce(0) 定时器足够时间，
    // 若被错误调度此刻必然发出；不手动 flush。
    await new Promise((r) => setTimeout(r, 20))
    expect(server.patchCalls.length).toBe(0)

    // 而 portable 变更会触发
    useAppSettings.getState().update({ accentColor: '#5a9e6f' })
    await flush()
    expect(server.patchCalls.length).toBe(1)
    expect(server.patchCalls[0].accentColor).toBe('#5a9e6f')
    expect(server.patchCalls[0]).not.toHaveProperty('sidebarWidth')
  })
})

describe('resetReader — 只重置 Reader 子集并同步默认值', () => {
  it('重置后 Reader 数值回默认，非 Reader 设置不动；默认值同步到 server', async () => {
    const server = makeServer()
    server.stored = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    useAppSettings.getState().update({
      readerFontSize: 28,
      themeMode: 'dark',
      accentColor: '#5a9e6f',
      sidebarWidth: 260,
    })
    await flush()

    useAppSettings.getState().resetReader()
    await flush()

    const s = useAppSettings.getState().settings
    expect(s.readerFontSize).toBe(17) // reader 默认
    expect(s.readerParagraphSpacing).toBe(0.85)
    expect(s.readerPageMargin).toBe(32)
    expect(s.themeMode).toBe('dark') // 非 reader 设置保留
    expect(s.accentColor).toBe('#5a9e6f')
    expect(s.sidebarWidth).toBe(260)
  })
})
