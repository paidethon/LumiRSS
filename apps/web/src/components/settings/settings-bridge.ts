/** settings-bridge — 设置壳与设置页内容之间的最小桥。
 *
 * 分类页内容（categories.tsx 声明式条目）拿不到 SettingsModal 的
 * onClose；当某个设置项需要跳转到应用主界面（如「打开订阅中心」）时，
 * 通过这个窗口事件请求关闭设置壳（桌面 Modal 与移动全屏页都监听）。
 *
 * P0-12：反向入口——主界面导航（侧栏「API 来源」「邮件简报」）请求
 * 打开设置壳并直达指定分类（同窗口事件模式，无全局 store、无路由
 * 依赖；桌面 Modal 与移动全屏页消费同一 detail.category）。同一分类
 * 重复请求也生效（seq 递增，消费方以对象身份判断变化）。
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

export interface SettingsOpenDetail {
  /** 目标分类 id；未知/缺省由消费方降级为默认分类。 */
  category?: string
  /** 每次请求递增，消费方据此对同一分类的重复请求也做出反应。 */
  seq: number
}

const SETTINGS_OPEN_EVENT = 'lumi:open-settings'

let openSeq = 0

/** 请求打开设置（可选直达分类）：主界面导航入口使用。 */
export function requestOpenSettings(category?: string): void {
  if (typeof window !== 'undefined') {
    openSeq += 1
    window.dispatchEvent(
      new CustomEvent<SettingsOpenDetail>(SETTINGS_OPEN_EVENT, {
        detail: { category, seq: openSeq },
      }),
    )
  }
}

export function onOpenSettingsRequest(
  handler: (detail: SettingsOpenDetail) => void,
): () => void {
  if (typeof window === 'undefined') return () => {}
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<SettingsOpenDetail>).detail
    handler(detail ?? { seq: 0 })
  }
  window.addEventListener(SETTINGS_OPEN_EVENT, listener)
  return () => window.removeEventListener(SETTINGS_OPEN_EVENT, listener)
}
