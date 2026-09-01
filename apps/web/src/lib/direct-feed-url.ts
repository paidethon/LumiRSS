/** direct-feed-url — 0013 Gate 2 的输入边界（前端第一道，BFF 仍全量校验）。
 *
 * 0013 只接受「直接 RSS/Atom URL」：必须是绝对 http(s) 地址。这里做
 * 纯结构判断（快速给出诚实提示，省一次无意义请求）；SSRF / DNS /
 * 私有地址等安全校验属于 BFF safe-fetch boundary（feed_preview.py），
 * 前端不重复实现。feed 内容是否真的是 RSS/Atom 由 BFF 预览判定。 */

/** 是否是绝对 http(s) URL（可提交给 BFF 预览的最小形状）。 */
export function isDirectFeedUrl(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === '' || trimmed.length > 2048) return false
  try {
    const url = new URL(trimmed)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}
