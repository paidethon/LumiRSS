/** settings-bridge — 设置壳与设置页内容之间的最小桥。
 *
 * 分类页内容（categories.tsx 声明式条目）拿不到 SettingsModal 的
 * onClose；当某个设置项需要跳转到应用主界面（如「打开订阅中心」）时，
 * 通过这个窗口事件请求关闭设置壳（桌面 Modal 与移动全屏页都监听）。
 */

const SETTINGS_CLOSE_EVENT = 'lumi:close-settings'

export function requestCloseSettings(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(SETTINGS_CLOSE_EVENT))
  }
}

export function onCloseSettingsRequest(handler: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(SETTINGS_CLOSE_EVENT, handler)
  return () => window.removeEventListener(SETTINGS_CLOSE_EVENT, handler)
}
