/** app-settings store 测试 — 0010 Gate A（AC17/V11）。 */

import { describe, expect, it } from 'vitest'
import {
  type AppSettings,
  DEFAULT_APP_SETTINGS,
  SETTINGS_STORAGE_KEY,
  loadSettings,
  normalizeSettings,
  persistSettings,
} from '../store/app-settings'

function fakeStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    get length() {
      return map.size
    },
  } as Storage
}

describe('normalizeSettings — 不可信输入逐字段归一化', () => {
  it('null / 非对象 → 全默认', () => {
    expect(normalizeSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
    expect(normalizeSettings('garbage')).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('合法值全部保留', () => {
    const valid: AppSettings = {
      ...DEFAULT_APP_SETTINGS,
      sidebarHideRead: true,
      timelineUnreadDot: false,
      themeMode: 'dark',
      readerBackground: 'sepia',
      readerFontSize: 21,
      readerLineHeight: 1.65,
      readerContentWidth: 900,
      sidebarWidth: 300,
      timelineWidth: 460,
    }
    expect(normalizeSettings(valid)).toEqual(valid)
  })

  it('非法枚举回退默认（不抛错）', () => {
    const bad = normalizeSettings({
      language: 'en-US',
      themeMode: 'blue',
      readerBackground: 'not-a-bg',
      readerFontSize: 33,
      readerLineHeight: 9.9,
      readerContentWidth: 123,
    })
    expect(bad.language).toBe('zh-CN')
    expect(bad.themeMode).toBe('system')
    expect(bad.readerBackground).toBe('follow')
    expect(bad.readerFontSize).toBe(17)
    expect(bad.readerLineHeight).toBe(1.85)
    expect(bad.readerContentWidth).toBe(760)
  })

  it('分栏宽度 clamp 到边界内', () => {
    const clamped = normalizeSettings({ sidebarWidth: 50, timelineWidth: 9999 })
    expect(clamped.sidebarWidth).toBe(220)
    expect(clamped.timelineWidth).toBe(460)
  })

  it('未知字段丢弃', () => {
    const result = normalizeSettings({ ...DEFAULT_APP_SETTINGS, evil: '<script>' })
    expect((result as unknown as Record<string, unknown>).evil).toBeUndefined()
  })
})

describe('loadSettings — 新 key 读取与旧 key 迁移（V11）', () => {
  it('storage 为 null → 默认', () => {
    expect(loadSettings(null)).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('无任何 key → 默认（不写入）', () => {
    expect(loadSettings(fakeStorage())).toEqual(DEFAULT_APP_SETTINGS)
  })

  it('新 key 存在 → 直接读取（不触发迁移）', () => {
    const s = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'dark', readerFontSize: 19 }),
    })
    expect(loadSettings(s).themeMode).toBe('dark')
    expect(loadSettings(s).readerFontSize).toBe(19)
  })

  it('旧 key 迁移：lumirss-theme + lumirss-reader-bg 并入（AC17）', () => {
    const s = fakeStorage({
      'lumirss-theme': 'dark',
      'lumirss-reader-bg': 'sepia',
    })
    const migrated = loadSettings(s)
    expect(migrated.themeMode).toBe('dark')
    expect(migrated.readerBackground).toBe('sepia')
    // 其余字段保持默认
    expect(migrated.readerFontSize).toBe(DEFAULT_APP_SETTINGS.readerFontSize)
  })

  it('旧 key 非法值 → 忽略迁移', () => {
    const s = fakeStorage({ 'lumirss-theme': 'purple', 'lumirss-reader-bg': 'not-a-bg' })
    expect(loadSettings(s).themeMode).toBe('system')
    expect(loadSettings(s).readerBackground).toBe('follow')
  })

  it('损坏 JSON → 回退默认不抛错', () => {
    const s = fakeStorage({ [SETTINGS_STORAGE_KEY]: '{broken' })
    expect(loadSettings(s)).toEqual(DEFAULT_APP_SETTINGS)
  })
})

describe('persistSettings 往返', () => {
  it('写 → 读完全一致', () => {
    const s = fakeStorage()
    const custom: AppSettings = { ...DEFAULT_APP_SETTINGS, readerFontSize: 21, themeMode: 'light' }
    persistSettings(s, custom)
    expect(loadSettings(s)).toEqual(custom)
  })
})

describe('store update（集成）', () => {
  it('update 局部合并 + 持久化 + 归一化', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    useAppSettings.getState().update({ readerFontSize: 19 })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(19)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(19)
    // 非法值经 update 也被归一化
    useAppSettings.getState().update({ readerFontSize: 99 as never })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(17)
    localStorage.clear()
  })

  it('reset 恢复全部默认', async () => {
    const { useAppSettings } = await import('../store/app-settings')
    localStorage.clear()
    useAppSettings.getState().update({ themeMode: 'dark', sidebarHideRead: true })
    useAppSettings.getState().reset()
    expect(useAppSettings.getState().settings).toEqual(DEFAULT_APP_SETTINGS)
    localStorage.clear()
  })
})
