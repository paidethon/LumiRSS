/** R25 — 业务状态云端同步扩展：新 portable 键 + 断网补传队列 + 升级迁移。
 *
 * - 新键（工具栏 order / 阅读模式 / 朗读全套 / 布局宽度等）随 portable
 *   同步 PATCH；数组键（'-id' 占位）按内容比较、原样透传；
 * - 断网补传：PATCH 失败 → pending 队列（dirty 键标记，内存 +
 *   localStorage）；失败期间同键后写覆盖先写；online 事件按序重放，
 *   服务端只落最新值；恢复后队列清空、计数归零；
 * - 退出登录（resetAccountSettingsSync，auth-reset 统一挂钩点）清空队列；
 * - 升级迁移：服务端 storedKeys 不在册的键保留本地值，与默认不同则
 *   上传为初始云值；在册键 server-wins；旧服务端（无 storedKeys 字段）
 *   保持历史 server-wins 行为；
 * - 设置·账户页「待同步更改」轻提示 + 立即重试。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AccountSecuritySection } from '../components/settings/AccountSecuritySection'
import {
  DEFAULT_APP_SETTINGS,
  normalizeSettings,
  useAppSettings,
} from '../store/app-settings'
import { useSettingsConflict } from '../store/settings-conflict'
import { normalizeReaderToolbarOrder } from '../lib/reader-toolbar'
import {
  flushSettingsSyncForTests,
  getPendingSettingsSyncCount,
  initSettingsSync,
  resetAccountSettingsSync,
  resetSettingsSyncForTests,
  subscribePendingSettingsSync,
} from '../store/settings-sync'
import { useAuthStore } from '../store/auth'
import type { ServerSettings } from '../api/types'

function makeServer(): {
  stored: boolean
  doc: Partial<ServerSettings>
  storedKeys: string[]
  patchCalls: Record<string, unknown>[]
  failPatch: boolean
  revision: number
  exposeStoredKeys: boolean
} {
  return {
    stored: false,
    doc: {},
    storedKeys: [],
    patchCalls: [],
    failPatch: false,
    revision: 0,
    exposeStoredKeys: true,
  }
}

function stubFetch(server: ReturnType<typeof makeServer>) {
  const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
    const path = String(url)
    if (path === '/api/v1/settings') {
      const method = init?.method ?? 'GET'
      if (method === 'GET') {
        return new Response(
          JSON.stringify({
            schemaVersion: 1,
            stored: server.stored,
            revision: server.revision,
            // R25：storedKeys 字段（exposeStoredKeys=false 模拟旧服务端）
            ...(server.exposeStoredKeys ? { storedKeys: server.storedKeys } : {}),
            ...server.doc,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (method === 'PATCH') {
        if (server.failPatch) {
          return new Response(JSON.stringify({ error: { type: 'network', message: 'down' } }), {
            status: 502,
          })
        }
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
        server.patchCalls.push(body)
        server.stored = true
        for (const [key, value] of Object.entries(body)) {
          if (key === 'baseRevision') continue
          ;(server.doc as Record<string, unknown>)[key] = value
          if (!server.storedKeys.includes(key)) server.storedKeys.push(key)
        }
        server.storedKeys.sort()
        server.revision += 1
        return new Response(
          JSON.stringify({
            schemaVersion: 1,
            stored: true,
            revision: server.revision,
            storedKeys: server.storedKeys,
            ...server.doc,
          }),
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
  useSettingsConflict.getState().clearConflict()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetSettingsSyncForTests()
})

describe('R25 新 portable 键同步', () => {
  it('工具栏 order 数组（含 -id 隐藏占位）与朗读/布局键随 PATCH 上云', async () => {
    const server = makeServer()
    server.stored = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    useAppSettings.getState().update({
      readerToolbarDesktopOrder: ['star', '-share', 'more'],
      speechRate: 1.25,
      speechSkipCode: true,
      sidebarWidth: 280,
      readerReadingMode: 'paged',
    })
    await flush()

    const patch = server.patchCalls.at(-1) ?? {}
    // PATCH 携带 normalize 后的完整序（缺项补全 + '-share' 隐藏占位居末；
    // 锁定动作 more 恒可见）
    expect(patch.readerToolbarDesktopOrder).toEqual(
      normalizeReaderToolbarOrder(['star', '-share', 'more'], 'desktop'),
    )
    expect(patch.readerToolbarDesktopOrder).toContain('-share')
    expect(patch.speechRate).toBe(1.25)
    expect(patch.speechSkipCode).toBe(true)
    expect(patch.sidebarWidth).toBe(280)
    expect(patch.readerReadingMode).toBe('paged')
    // 数组键按内容比较：无关 normalize 重建不产生 dirty/PATCH 循环
    const patchesBefore = server.patchCalls.length
    useAppSettings.getState().update({ themeMode: 'dark' })
    await flush()
    expect(useAppSettings.getState().settings.readerToolbarDesktopOrder).toEqual(
      normalizeReaderToolbarOrder(['star', '-share', 'more'], 'desktop'),
    )
    expect(server.patchCalls.length).toBeGreaterThanOrEqual(patchesBefore)
    const last = server.patchCalls.at(-1) ?? {}
    expect(last.readerToolbarDesktopOrder).toEqual(
      normalizeReaderToolbarOrder(['star', '-share', 'more'], 'desktop'),
    )
  })
})

describe('R25 断网补传队列', () => {
  it('PATCH 失败进 pending 队列（计数 + localStorage）；重放后写覆盖先写；成功清队', async () => {
    const server = makeServer()
    server.stored = true
    server.failPatch = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    const seen: number[] = []
    const unsubscribe = subscribePendingSettingsSync(() => seen.push(getPendingSettingsSyncCount()))

    // 失败期间连续两次改同一键：后写覆盖先写（队列只留最新意图）
    useAppSettings.getState().update({ sidebarWidth: 260 })
    await flush()
    expect(getPendingSettingsSyncCount()).toBeGreaterThan(0)
    useAppSettings.getState().update({ sidebarWidth: 290 })
    await flush()

    // 失败不回滚 + 标记持久化（跨重载存活）
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(290)
    expect(JSON.parse(localStorage.getItem('lumirss-settings-dirty')!)).toContain('sidebarWidth')
    expect(seen.at(-1)).toBeGreaterThan(0)

    // 恢复网络 → online 事件按序重放 → 服务端只落最新值 → 队列清空
    server.failPatch = false
    window.dispatchEvent(new Event('online'))
    await vi.waitFor(() => expect(server.doc.sidebarWidth).toBe(290))
    await vi.waitFor(() => expect(getPendingSettingsSyncCount()).toBe(0))
    expect(localStorage.getItem('lumirss-settings-dirty')).toBeNull()
    expect(seen.at(-1)).toBe(0)
    unsubscribe()
  })

  it('retryPendingSettingsSync 立即补传；无 pending 时为 no-op（不发请求）', async () => {
    const server = makeServer()
    server.stored = true
    server.failPatch = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    const { retryPendingSettingsSync } = await import('../store/settings-sync')
    const patchesBefore = server.patchCalls.length
    await retryPendingSettingsSync() // 无 pending：不发请求
    expect(server.patchCalls.length).toBe(patchesBefore)

    useAppSettings.getState().update({ timelineWidth: 440 })
    await flush()
    expect(server.doc.timelineWidth).toBeUndefined()

    server.failPatch = false
    await retryPendingSettingsSync()
    await vi.waitFor(() => expect(server.doc.timelineWidth).toBe(440))
    expect(getPendingSettingsSyncCount()).toBe(0)
  })

  it('退出登录（resetAccountSettingsSync）清空 pending 队列与持久化标记', async () => {
    const server = makeServer()
    server.stored = true
    server.failPatch = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    useAppSettings.getState().update({ speechVoiceURI: 'urn:example:voice' })
    await flush()
    expect(getPendingSettingsSyncCount()).toBeGreaterThan(0)

    // auth-reset 的统一挂钩点（O157）：lib/auth-reset.ts 在登出/换号时
    // 调用本函数——A 的未落库意图不得变成对 B 的 PATCH。
    resetAccountSettingsSync()
    expect(getPendingSettingsSyncCount()).toBe(0)
    expect(localStorage.getItem('lumirss-settings-dirty')).toBeNull()
    // portable 值回默认（账号投影归零）
    expect(useAppSettings.getState().settings.speechVoiceURI).toBe('')
  })
})

describe('R25 升级迁移 — storedKeys 在册/不在册语义', () => {
  it('不在册的新键保留本地值，与默认不同则上传为初始云值', async () => {
    // 模拟升级：服务端文档只存过旧键（readerFontSize），本地已有
    // 新键偏好 sidebarWidth=280（≠ 默认 240）
    useAppSettings.getState().update({ sidebarWidth: 280 })
    const server = makeServer()
    server.stored = true
    server.doc = { readerFontSize: 20 }
    server.storedKeys = ['readerFontSize']
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })

    // 本地 280 不被模型默认 240 覆盖
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(20))
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(280)
    // 且本地上传为初始云值（PATCH 携带），成功后队列清空
    await vi.waitFor(() => expect(server.doc.sidebarWidth).toBe(280))
    await vi.waitFor(() => expect(getPendingSettingsSyncCount()).toBe(0))
    const seed = server.patchCalls.find((p) => p.sidebarWidth === 280)
    expect(seed).toBeDefined()
  })

  it('在册键 server-wins；与默认相同的不在册键不上传', async () => {
    // 本地新键值 = 默认（240）：不在册 → 保留本地（无意义上传）
    const server = makeServer()
    server.stored = true
    server.doc = { readerReadingMode: 'paged', sidebarWidth: 300 }
    server.storedKeys = ['readerReadingMode', 'sidebarWidth']
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })

    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerReadingMode).toBe('paged'))
    // 在册键采用服务端值
    expect(useAppSettings.getState().settings.sidebarWidth).toBe(300)
    // 不在册且等于默认 → 不产生迁移 PATCH
    await new Promise((r) => setTimeout(r, 20))
    expect(server.patchCalls.length).toBe(0)
    expect(getPendingSettingsSyncCount()).toBe(0)
  })

  it('旧服务端（无 storedKeys 字段）保持历史 server-wins 行为', async () => {
    useAppSettings.getState().update({ sidebarWidth: 280 })
    const server = makeServer()
    server.stored = true
    server.doc = { sidebarWidth: 240 }
    server.exposeStoredKeys = false
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.sidebarWidth).toBe(240))
    await new Promise((r) => setTimeout(r, 20))
    expect(server.patchCalls.length).toBe(0)
  })
})

describe('R25 设置·账户页待同步轻提示', () => {
  it('有未落库变更时显示「待同步更改」，重试成功后消失', async () => {
    useAuthStore.getState().setMode('session')
    useAuthStore.getState().setStatus('authenticated')
    const server = makeServer()
    server.stored = true
    server.failPatch = true
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(17))

    useAppSettings.getState().update({ sidebarWidth: 280, speechRate: 1.5 })
    await flush()
    expect(getPendingSettingsSyncCount()).toBe(2)

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    render(
      <QueryClientProvider client={qc}>
        <AccountSecuritySection />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText('待同步更改')).toBeTruthy())
    expect(screen.getByText(/有 2 项偏好更改尚未同步到云端/)).toBeTruthy()

    // 恢复网络 → 立即重试 → 补传成功 → 提示消失
    server.failPatch = false
    fireEvent.click(screen.getByRole('button', { name: '立即重试' }))
    await waitFor(() => expect(server.doc.sidebarWidth).toBe(280))
    await waitFor(() => expect(screen.queryByText('待同步更改')).toBeNull())
  })
})

describe('R25 normalize 覆盖全部 portable 键（防漂移回归）', () => {
  it('normalizeSettings(null) 深等于 DEFAULT_APP_SETTINGS（含 R21 迁移标记键）', () => {
    expect(normalizeSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
    expect(DEFAULT_APP_SETTINGS.translationMigratedFromLibre).toBe(false)
  })

  it('hydration/同步往返不产生脏值：portable 快照可被 normalize 恒等还原', () => {
    const mutated = normalizeSettings({
      ...DEFAULT_APP_SETTINGS,
      readerToolbarMobileOrder: ['-print', 'star'],
      speechLexicon: [{ match: 'API', replace: 'A.P.I.' }],
      filterRules: [
        { id: 'r1', keyword: '广告', feedId: null, type: 'keyword', enabled: true },
      ],
    })
    // 二次归一化必须幂等（否则同步订阅会永久误报 dirty）
    expect(normalizeSettings(mutated)).toEqual(mutated)
  })
})
