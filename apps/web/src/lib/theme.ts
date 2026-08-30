/** 主题纯逻辑 — 0009 Gate 1。
 *
 * 三态模式（system / light / dark）→ 实际主题（light / dark）的解析，
 * 以及 localStorage 持久化与 <html data-theme> 挂载。
 * 全部为可测试的纯函数 + 最小的 DOM 副作用；React 绑定在
 * store/theme.ts（Zustand）。
 *
 * 持久化是临时方案（Spec AC5）：非敏感外观偏好存 localStorage，
 * 0017 统一设置时迁移到服务端。 */

export type ThemeMode = 'system' | 'light' | 'dark'
export type Theme = 'light' | 'dark'

/** localStorage key（index.html 的防闪烁脚本读同一个 key） */
export const THEME_STORAGE_KEY = 'lumirss-theme'

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'system' || value === 'light' || value === 'dark'
}

/** 三态 → 实际主题。system 跟随 prefers-color-scheme。 */
export function resolveTheme(mode: ThemeMode, prefersDark: boolean): Theme {
  if (mode === 'light' || mode === 'dark') return mode
  return prefersDark ? 'dark' : 'light'
}

/** 读取持久化偏好；无效/缺失值一律回退 system（不抛错）。 */
export function readStoredMode(storage: Storage | null): ThemeMode {
  if (storage === null) return 'system'
  try {
    const raw = storage.getItem(THEME_STORAGE_KEY)
    return isThemeMode(raw) ? raw : 'system'
  } catch {
    // 隐私模式 / storage 被禁用时静默回退
    return 'system'
  }
}

export function writeStoredMode(storage: Storage | null, mode: ThemeMode): void {
  if (storage === null) return
  try {
    storage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // 写失败不影响功能：本次会话内主题仍然生效
  }
}

/** 把实际主题挂到 <html data-theme>（themes.css 的选择器）。 */
export function applyTheme(
  element: HTMLElement,
  theme: Theme,
): void {
  element.setAttribute('data-theme', theme)
}

/** 浏览器环境的 matchMedia（jsdom / SSR 安全包装）。 */
export function prefersDarkScheme(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 浏览器启动路径：读偏好 → 解析 → 挂载（main.tsx 调一次）。 */
export function initTheme(): void {
  if (typeof document === 'undefined') return
  const mode = readStoredMode(typeof localStorage === 'undefined' ? null : localStorage)
  applyTheme(document.documentElement, resolveTheme(mode, prefersDarkScheme()))
}
