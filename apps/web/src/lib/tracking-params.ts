/** F010 外链追踪参数清理 —— stripTrackingParams（保守清单）。
 *
 * 移除（仅此清单）：utm_*（utm_source/utm_medium/…）、fbclid、gclid、
 * msclkid、igshid、mc_cid、mc_eid。
 * 绝不移除：签名/授权参数（*_signature、token、sig、key、access_token）
 * 与任何未知名单外参数（保守：宁可少清，不可破坏链接）。
 * URL 解析用 URL API，非 ASCII（CJK）查询值原样保留。 */

const TRACKING_EXACT = new Set(['fbclid', 'gclid', 'msclkid', 'igshid', 'mc_cid', 'mc_eid'])
const TRACKING_PREFIXES = ['utm_']

const PROTECTED_EXACT = new Set(['token', 'sig', 'key', 'access_token'])

export function isTrackingParam(name: string): boolean {
  const lowered = name.toLowerCase()
  if (PROTECTED_EXACT.has(lowered)) return false
  if (lowered.endsWith('_signature')) return false
  if (TRACKING_EXACT.has(lowered)) return true
  return TRACKING_PREFIXES.some((prefix) => lowered.startsWith(prefix))
}

export interface StripResult {
  /** 清理后的 URL（无可移除参数时与输入一致——不重写无关部分）。 */
  url: string
  /** 被移除的参数名（按出现顺序；预览用）。 */
  removed: string[]
}

/** 清理追踪参数；解析失败或非 http(s) → 原样返回（removed=[]）。 */
export function stripTrackingParams(url: string): StripResult {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return { url, removed: [] }
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return { url, removed: [] }
  }
  const removed: string[] = []
  for (const name of Array.from(parsed.searchParams.keys())) {
    if (isTrackingParam(name)) removed.push(name)
  }
  if (removed.length === 0) return { url, removed }
  for (const name of removed) {
    // 同名多值全部移除
    parsed.searchParams.delete(name)
  }
  return { url: parsed.toString(), removed }
}
