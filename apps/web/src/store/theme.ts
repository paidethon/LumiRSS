/** 主题 UI state — 0009 Gate 1。
 *
 * 只放"用户选了哪个模式"（system / light / dark）这一个状态；
 * 颜色本体全部在 CSS token（styles/themes.css）。切模式时同步
 * localStorage + <html data-theme>；system 模式下监听系统偏好变化。
 * 临时 UI（切换器）在 dev playground；正式入口 Gate 4 起进入设置。 */

import { create } from 'zustand'
import {
  type ThemeMode,
  applyTheme,
  prefersDarkScheme,
  readStoredMode,
  resolveTheme,
  writeStoredMode,
} from '../lib/theme'

interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

function storage(): Storage | null {
  return typeof localStorage === 'undefined' ? null : localStorage
}

/** 把当前模式（或指定模式）应用到 DOM。 */
function sync(mode: ThemeMode): void {
  if (typeof document === 'undefined') return
  applyTheme(document.documentElement, resolveTheme(mode, prefersDarkScheme()))
}

export const useTheme = create<ThemeState>((set) => ({
  mode: readStoredMode(storage()),
  setMode: (mode) => {
    writeStoredMode(storage(), mode)
    sync(mode)
    set({ mode })
  },
}))

/** system 模式下跟随系统偏好变化（main.tsx 调一次；jsdom 安全）。 */
export function watchSystemTheme(): void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return
  }
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => {
      const { mode } = useTheme.getState()
      if (mode === 'system') sync(mode)
    })
}
