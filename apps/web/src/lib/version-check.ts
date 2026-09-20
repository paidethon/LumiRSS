/** version-check — F117 前端版本更新确认。
 *
 * App 每 30 分钟 fetch `/version.json`（静态文件；构建注入
 * `__APP_BUILD__`）并与当前构建比较：
 * - 版本不同 → 触发一次「发现新版本 [立即更新/稍后]」确认（不自动刷新）；
 * - 「立即更新」：若有活跃草稿（draft-store 标记的注册表单草稿）→
 *   先弹「有未保存草稿」保护确认（草稿本就本地持久，确认后刷新不丢）；
 *   更新 = location.reload；
 * - 404 / 网络失败 → 静默跳过；
 * - /api/* 认证响应永不经过该机制（fetch 只打 /version.json）。 */

import { listDraftKeysOf } from './draft-store-internal'

export const APP_BUILD: string =
  typeof __APP_BUILD__ !== 'undefined' ? __APP_BUILD__ : 'dev'

const POLL_MS = 30 * 60 * 1000

export interface VersionCheckHandlers {
  onNewVersion: (build: string) => void
}

let timer: ReturnType<typeof setInterval> | null = null
let dismissedBuild: string | null = null

/** 单次检查：版本不同且未忽略 → onNewVersion(build)。返回远端 build。 */
export async function checkVersionOnce(
  handlers: VersionCheckHandlers,
  fetchFn: typeof fetch = fetch,
): Promise<string | null> {
  try {
    const response = await fetchFn('/version.json', {
      headers: { 'cache-control': 'no-cache' },
    })
    if (!response.ok) return null // 404（dev/preview 未生成）→ 静默跳过
    const data = (await response.json()) as { build?: unknown }
    if (typeof data.build !== 'string' || data.build === '') return null
    if (data.build !== APP_BUILD && data.build !== dismissedBuild) {
      handlers.onNewVersion(data.build)
    }
    return data.build
  } catch {
    return null // 网络失败静默
  }
}

/** 「稍后」：本会话内不再为该版本提示。 */
export function dismissVersion(build: string): void {
  dismissedBuild = build
}

/** 立即更新：有活跃草稿 → 需要先过保护确认（返回 'confirm-draft'）；
 * 否则直接刷新。reload 参数是测试接缝（默认真实 location.reload）。 */
export function applyUpdate(reload: () => void = () => location.reload()): 'reload' | 'confirm-draft' {
  if (hasActiveDrafts()) return 'confirm-draft'
  reload()
  return 'reload'
}

/** 有活跃草稿：localStorage 里存在任意注册表单的草稿键。 */
export function hasActiveDrafts(): boolean {
  return listDraftKeysOf().length > 0
}

/** 启动轮询（App 挂载一次；返回清理函数）。 */
export function startVersionCheck(handlers: VersionCheckHandlers): () => void {
  void checkVersionOnce(handlers)
  timer = setInterval(() => {
    void checkVersionOnce(handlers)
  }, POLL_MS)
  return () => {
    if (timer !== null) clearInterval(timer)
    timer = null
  }
}
