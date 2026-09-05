/** AUDIT-008：规范主题系统监听（store/app-settings.watchSystemTheme）。
 *
 * 验证：OS 偏好变化时，system 模式跟随；显式 light/dark 绝不被 OS 覆盖。
 * watchSystemTheme 只挂一次监听（模块级幂等），因此本文件用单个测试串起
 * 两个场景，避免重复挂载被守卫拦截。 */

import { beforeEach, describe, expect, it } from 'vitest'
import { useAppSettings, watchSystemTheme } from '../store/app-settings'

type Listener = () => void
let darkListeners: Listener[] = []
let prefersDark = false

function installMatchMediaMock() {
  darkListeners = []
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: query.includes('prefers-color-scheme: dark') ? prefersDark : false,
      media: query,
      onchange: null,
      addEventListener: (_type: string, cb: Listener) => {
        if (query.includes('prefers-color-scheme: dark')) darkListeners.push(cb)
      },
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

function fireOsChange() {
  for (const cb of darkListeners) cb()
}

function dataTheme(): string | null {
  return document.documentElement.getAttribute('data-theme')
}

beforeEach(() => {
  localStorage.clear()
  prefersDark = false
  installMatchMediaMock()
  useAppSettings.getState().reset()
})

describe('watchSystemTheme（规范主题系统监听）', () => {
  it('显式 dark 不被 OS 变化覆盖；切到 system 后跟随 OS', () => {
    // 显式 dark：OS 当前为 light，仍是 dark
    useAppSettings.getState().update({ themeMode: 'dark' })
    expect(dataTheme()).toBe('dark')

    // 挂载规范监听（捕获 change 回调）
    watchSystemTheme()
    expect(darkListeners.length).toBeGreaterThan(0)

    // OS 翻到 dark 再翻回 light：显式 dark 恒为 dark，绝不被覆盖
    prefersDark = true
    fireOsChange()
    expect(dataTheme()).toBe('dark')
    prefersDark = false
    fireOsChange()
    expect(dataTheme()).toBe('dark')

    // 切到 system：立即跟随当前 OS（light）
    useAppSettings.getState().update({ themeMode: 'system' })
    expect(dataTheme()).toBe('light')

    // OS 翻到 dark：system 模式跟随
    prefersDark = true
    fireOsChange()
    expect(dataTheme()).toBe('dark')

    // 再显式 light：OS 仍为 dark，但显式 light 胜出且不被后续 OS 变化覆盖
    useAppSettings.getState().update({ themeMode: 'light' })
    expect(dataTheme()).toBe('light')
    prefersDark = false
    fireOsChange()
    expect(dataTheme()).toBe('light')
  })
})
