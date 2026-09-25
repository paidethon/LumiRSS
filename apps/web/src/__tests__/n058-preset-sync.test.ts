/** N058 阅读样式预设进 portable 同步测试。
 *
 * - sync up：用户预设（含版本标签 schemaVersion）随 portable PATCH
 *   上送（剥离设备本地字段 builtin）；
 * - sync down：hydration 用 server 预设覆盖本地（可正常应用）；
 * - device params not clobbered：预设同步/应用不触碰设备本地键
 *   （readerBackgroundImage / readerPresetId 等不进 portable payload）；
 * - deviceScope 守卫：mobile 应用 desktop-only 预设忽略宽度/栏数
 *   （applyPresetForDevice 既有行为与同步解耦）。 */

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import {
  PORTABLE_KEYS,
  portableSettings,
  useAppSettings,
  type ReaderPreset,
} from '../store/app-settings'
import {
  applyPresetForDevice,
  PRESET_SCHEMA_VERSION,
} from '../lib/reader-preset-device'
import {
  flushSettingsSyncForTests,
  initSettingsSync,
  resetSettingsSyncForTests,
} from '../store/settings-sync'
import type { ServerSettings } from '../api/types'

function makeServer(): {
  stored: boolean
  doc: Partial<ServerSettings>
  patchCalls: Record<string, unknown>[]
  revision: number
} {
  return { stored: false, doc: {}, patchCalls: [], revision: 0 }
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
            ...server.doc,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      server.patchCalls.push(body)
      server.stored = true
      server.doc = { ...server.doc, ...body } as Partial<ServerSettings>
      server.revision += 1
      return new Response(
        JSON.stringify({
          schemaVersion: 1,
          stored: true,
          revision: server.revision,
          ...server.doc,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    }
    return new Response(JSON.stringify({ error: { type: 'not_found' } }), { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const flush = () => flushSettingsSyncForTests()

function makePreset(id: string, name: string, desktopOnly = false): ReaderPreset {
  return {
    id,
    name,
    builtin: false,
    schemaVersion: PRESET_SCHEMA_VERSION,
    vars: {
      readerFontFamily: 'serif',
      readerFontSize: 21,
      readerLineHeight: 1.9,
      readerBackground: 'paper',
      readerParagraphSpacing: 1.2,
      readerJustify: true,
      readerContentWidth: 820,
      readerColumns: 2,
      deviceScope: desktopOnly ? 'desktop' : 'all',
    },
  }
}

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

describe('N058 预设 portable 同步', () => {
  it('readerPresets 在 PORTABLE_KEYS 内且上送剥离 builtin', async () => {
    expect(PORTABLE_KEYS).toContain('readerPresets')

    const server = makeServer()
    stubFetch(server)
    useAppSettings.getState().update({ readerPresets: [makePreset('p1', '夜间长文')] })

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(server.patchCalls.length).toBeGreaterThan(0))
    await flush()

    const payload = server.patchCalls[server.patchCalls.length - 1]
    const presets = payload.readerPresets as Array<Record<string, unknown>>
    expect(Array.isArray(presets)).toBe(true)
    expect(presets).toHaveLength(1)
    expect(presets[0]).toMatchObject({ id: 'p1', name: '夜间长文' })
    expect(presets[0].schemaVersion).toBe(PRESET_SCHEMA_VERSION) // 版本标签
    expect(presets[0].vars).toMatchObject({ readerFontSize: 21, deviceScope: 'all' })
    expect(presets[0]).not.toHaveProperty('builtin') // 设备本地字段剥离
  })

  it('sync down：server 预设覆盖本地并可被归一化应用', async () => {
    const server = makeServer()
    server.stored = true
    server.doc = {
      readerPresets: [
        {
          id: 'srv-1',
          name: '服务器预设',
          schemaVersion: PRESET_SCHEMA_VERSION,
          vars: {
            readerFontFamily: 'mono',
            readerFontSize: 19,
            readerLineHeight: 1.8,
            readerBackground: 'mint',
            readerParagraphSpacing: 1,
            readerJustify: false,
            deviceScope: 'all',
          },
        },
      ],
    } as Partial<ServerSettings>
    stubFetch(server)

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() =>
      expect(useAppSettings.getState().settings.readerPresets).toHaveLength(1),
    )

    const synced = useAppSettings.getState().settings.readerPresets[0]
    expect(synced.id).toBe('srv-1')
    expect(synced.vars.readerFontFamily).toBe('mono')
    expect(synced.builtin).toBe(false) // normalizePresets 补设备本地标记
  })

  it('预设同步不 clobber 设备本地参数', async () => {
    const server = makeServer()
    stubFetch(server)
    // 设备本地图片与当前选中预设：不在 portable payload 内。
    useAppSettings.getState().update({
      readerBackgroundImage: 'data:image/png;base64,AAA',
      readerPresetId: 'default',
      readerPresets: [makePreset('p9', '另一预设')],
    })

    initSettingsSync({ debounceMs: 0 })
    await vi.waitFor(() => expect(server.patchCalls.length).toBeGreaterThan(0))
    await flush()

    const payload = server.patchCalls[server.patchCalls.length - 1]
    expect(payload).not.toHaveProperty('readerBackgroundImage')
    expect(payload).not.toHaveProperty('readerPresetId')
    // 同步后设备本地状态原样。
    const s = useAppSettings.getState().settings
    expect(s.readerBackgroundImage).toBe('data:image/png;base64,AAA')
    expect(s.readerPresetId).toBe('default')
  })

  it('deviceScope 仍在应用侧守卫设备专属参数（mobile 忽略宽度/栏数）', () => {
    const result = applyPresetForDevice(makePreset('d1', '桌面预设', true).vars, true)
    expect(result.vars.readerContentWidth).toBeUndefined()
    expect(result.vars.readerColumns).toBeUndefined()
    expect(result.notice).toContain('桌面端生效')
    const desktop = applyPresetForDevice(makePreset('d2', '全端', false).vars, false)
    expect(desktop.vars.readerContentWidth).toBe(820)
    expect(desktop.notice).toBeNull()
  })

  it('portableSettings 序列化稳定（重复调用内容一致，避免脏标记循环）', () => {
    useAppSettings.getState().update({ readerPresets: [makePreset('p2', '稳定预设')] })
    const a = portableSettings(useAppSettings.getState().settings)
    const b = portableSettings(useAppSettings.getState().settings)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
  })
})
