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

/** 规范设置 key（app-settings.ts 的 SETTINGS_STORAGE_KEY；index.html 内联
 * 脚本与此处都硬编码同一字面量，避免 lib/theme ↔ store/app-settings 循环依赖）。 */
export const SETTINGS_STORAGE_KEY = 'lumirss-settings'

/** AUDIT-008：首帧主题解析（index.html 内联防闪烁脚本镜像同一逻辑）。
 *
 * 单一真源是规范 key ``lumirss-settings`` 的 ``themeMode``；仅当它缺失/无效时
 * 才回退到旧 key ``lumirss-theme``（迁移安全）。显式 light/dark 直接采用，
 * system/缺失按 OS 偏好解析。这样首帧一定使用「当前设置」，不会因旧 key
 * 与规范 key 分叉而闪错误主题。 */
export function resolveInitialTheme(
  storage: Storage | null,
  prefersDark: boolean,
): Theme {
  let mode: ThemeMode | null = null
  if (storage !== null) {
    try {
      const rawSettings = storage.getItem(SETTINGS_STORAGE_KEY)
      if (rawSettings !== null) {
        const parsed = JSON.parse(rawSettings) as { themeMode?: unknown }
        if (isThemeMode(parsed?.themeMode)) mode = parsed.themeMode
      }
    } catch {
      mode = null
    }
    if (mode === null) {
      const legacy = storage.getItem(THEME_STORAGE_KEY)
      if (isThemeMode(legacy)) mode = legacy
    }
  }
  return resolveTheme(mode ?? 'system', prefersDark)
}
