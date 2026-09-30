/** link-actions — NEW-358 链接操作面板（长按外链；纯逻辑核心）。
 *
 * 长按正文外链展示：域名、复制、稍后打开与已授权剪藏交接。
 * - 「稍后打开」= 本机暂存清单（localStorage `lumirss-link-later`，
 *   有界 50 条）——纯设备本地，绝不自动发起任何远端预览请求；
 * - 「剪藏」= 复用既有授权管线的一次性交接（sessionStorage
 *   `lumirss-share-url` + 跳转剪藏页预填）——抓取只发生在用户在剪藏页
 *   显式确认后（服务端 SSRF 钉住管线），本面板自身零网络；
 * - 域名解析：无效 URL → null（诚实显示不可用）。
 */

export const LINK_LATER_STORAGE_KEY = 'lumirss-link-later'
export const LINK_LATER_LIMIT = 50
/** 与 ClipsPage 的 PWA Share Target 交接同一键（一次性预填）。 */
export const CLIP_PREFILL_SESSION_KEY = 'lumirss-share-url'

export interface LinkLaterItem {
  url: string
  domain: string | null
  addedAt: number
}

/** 长按目标判定：跨源 http(s) 外链（与 content-links 的 external 同一
 * 语义；同源/锚点/passive/unsafe 不进面板）。 */
export function isExternalHttpUrl(href: string, baseURI: string): boolean {
  try {
    const resolved = new URL(href, baseURI)
    if (resolved.protocol !== 'http:' && resolved.protocol !== 'https:') return false
    if (typeof baseURI !== 'string' || baseURI === '') return true
    const base = new URL(baseURI)
    return resolved.origin !== base.origin
  } catch {
    return false
  }
}

/** 域名（invalid URL → null）。 */
export function linkDomain(url: string): string | null {
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

/** 读取本机「稍后打开」清单（损坏 → 空清单，诚实回退）。 */
export function readLinkLater(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): LinkLaterItem[] {
  if (storage === null) return []
  try {
    const raw = storage.getItem(LINK_LATER_STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const out: LinkLaterItem[] = []
    const seen = new Set<string>()
    for (const item of parsed) {
      if (item === null || typeof item !== 'object') continue
      const record = item as Record<string, unknown>
      if (typeof record.url !== 'string' || record.url === '' || seen.has(record.url)) continue
      seen.add(record.url)
      out.push({
        url: record.url,
        domain: typeof record.domain === 'string' && record.domain !== '' ? record.domain : null,
        addedAt: typeof record.addedAt === 'number' ? record.addedAt : 0,
      })
      if (out.length >= LINK_LATER_LIMIT) break
    }
    return out
  } catch {
    return []
  }
}

/** 加入「稍后打开」（已在清单 → 幂等 no-op；超限逐出最旧）。 */
export function addLinkLater(
  url: string,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null || url === '') return
  const items = readLinkLater(storage).filter((item) => item.url !== url)
  items.unshift({ url, domain: linkDomain(url), addedAt: Date.now() })
  try {
    storage.setItem(LINK_LATER_STORAGE_KEY, JSON.stringify(items.slice(0, LINK_LATER_LIMIT)))
  } catch {
    // 配额 / 隐私模式：本机暂存尽力而为。
  }
}

/** 移出「稍后打开」。 */
export function removeLinkLater(
  url: string,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  const items = readLinkLater(storage).filter((item) => item.url !== url)
  try {
    storage.setItem(LINK_LATER_STORAGE_KEY, JSON.stringify(items))
  } catch {
    // ignore
  }
}

/** 清空「稍后打开」。 */
export function clearLinkLater(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.removeItem(LINK_LATER_STORAGE_KEY)
  } catch {
    // ignore
  }
}

/** 剪藏交接：写入一次性预填键（与 PWA Share Target 同一通道）。
 * 返回是否写入成功；调用方随后跳转剪藏页——抓取只在用户显式确认后
 * 发生，本函数绝不发起网络请求。 */
export function stageClipPrefill(
  url: string,
  storage: Storage | null = typeof sessionStorage === 'undefined' ? null : sessionStorage,
): boolean {
  if (storage === null || url === '') return false
  try {
    storage.setItem(CLIP_PREFILL_SESSION_KEY, url)
    return true
  } catch {
    return false
  }
}
