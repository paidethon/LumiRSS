/** 主题纯逻辑测试 — 0009 Gate 1（AC4/AC5 的逻辑层）。 */

import { describe, expect, it } from 'vitest'
import {
  type ThemeMode,
  applyTheme,
  isThemeMode,
  readStoredMode,
  resolveTheme,
  resolveInitialTheme,
  writeStoredMode,
  THEME_STORAGE_KEY,
  SETTINGS_STORAGE_KEY,
} from '../lib/theme'

/** 模拟 Storage（jsdom 的 localStorage 可用，但显式 mock 更可控） */
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

describe('isThemeMode', () => {
  it('接受三个合法模式', () => {
    expect(isThemeMode('system')).toBe(true)
    expect(isThemeMode('light')).toBe(true)
    expect(isThemeMode('dark')).toBe(true)
  })
  it('拒绝非法值（无效持久化数据不致命）', () => {
    expect(isThemeMode('blue')).toBe(false)
    expect(isThemeMode(null)).toBe(false)
    expect(isThemeMode(undefined)).toBe(false)
    expect(isThemeMode('')).toBe(false)
  })
})

describe('resolveTheme', () => {
  it('显式 light/dark 优先于系统偏好', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
  it('system 跟随 prefers-color-scheme', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })
})

describe('readStoredMode', () => {
  it('缺失 / 无效值回退 system', () => {
    expect(readStoredMode(null)).toBe('system')
    expect(readStoredMode(fakeStorage())).toBe('system')
    expect(readStoredMode(fakeStorage({ [THEME_STORAGE_KEY]: 'garbage' }))).toBe(
      'system',
    )
  })
  it('读取合法持久化值', () => {
    expect(readStoredMode(fakeStorage({ [THEME_STORAGE_KEY]: 'dark' }))).toBe(
      'dark',
    )
    expect(readStoredMode(fakeStorage({ [THEME_STORAGE_KEY]: 'system' }))).toBe(
      'system',
    )
  })
})

describe('writeStoredMode + readStoredMode 往返', () => {
  it.each(['system', 'light', 'dark'] satisfies ThemeMode[])(
    '%s 可写可读',
    (mode) => {
      const s = fakeStorage()
      writeStoredMode(s, mode)
      expect(readStoredMode(s)).toBe(mode)
    },
  )
  it('storage 为 null 时写操作静默不抛错', () => {
    expect(() => writeStoredMode(null, 'dark')).not.toThrow()
  })
})

describe('applyTheme', () => {
  it('把实际主题挂到 data-theme 属性', () => {
    const el = document.createElement('html')
    applyTheme(el, 'dark')
    expect(el.getAttribute('data-theme')).toBe('dark')
    applyTheme(el, 'light')
    expect(el.getAttribute('data-theme')).toBe('light')
  })
})

describe('resolveInitialTheme（AUDIT-008 首帧单一真源）', () => {
  it('规范 key lumirss-settings.themeMode 优先于旧 key lumirss-theme', () => {
    const s = fakeStorage({
      [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'dark' }),
      [THEME_STORAGE_KEY]: 'light',
    })
    expect(resolveInitialTheme(s, false)).toBe('dark')
  })
  it('显式 light/dark 不被 OS 偏好覆盖', () => {
    const light = fakeStorage({ [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'light' }) })
    expect(resolveInitialTheme(light, true)).toBe('light') // OS dark，显式 light 胜
    const dark = fakeStorage({ [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'dark' }) })
    expect(resolveInitialTheme(dark, false)).toBe('dark') // OS light，显式 dark 胜
  })
  it('system 跟随 OS', () => {
    const s = fakeStorage({ [SETTINGS_STORAGE_KEY]: JSON.stringify({ themeMode: 'system' }) })
    expect(resolveInitialTheme(s, true)).toBe('dark')
    expect(resolveInitialTheme(s, false)).toBe('light')
  })
  it('规范 key 缺失时回退旧 key（迁移安全）', () => {
    const s = fakeStorage({ [THEME_STORAGE_KEY]: 'dark' })
    expect(resolveInitialTheme(s, false)).toBe('dark')
  })
  it('规范 key 为坏 JSON 时回退旧 key', () => {
    const s = fakeStorage({
      [SETTINGS_STORAGE_KEY]: '{not json',
      [THEME_STORAGE_KEY]: 'light',
    })
    expect(resolveInitialTheme(s, true)).toBe('light')
  })
  it('两者都缺失 → system → 跟随 OS；storage 为 null 安全', () => {
    expect(resolveInitialTheme(fakeStorage(), true)).toBe('dark')
    expect(resolveInitialTheme(null, false)).toBe('light')
  })
})

describe('store/theme（Zustand 绑定）', () => {
  it('setMode 同步 localStorage 与 data-theme', async () => {
    const { useTheme } = await import('../store/theme')
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    useTheme.getState().setMode('dark')
    expect(useTheme.getState().mode).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    // 恢复默认，避免影响其它测试
    useTheme.getState().setMode('system')
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })
})
