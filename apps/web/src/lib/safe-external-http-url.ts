/** safe-external-http-url — 「打开原文」链接的安全边界。
 *
 * EntryDetail.url 同样来自外部 RSS feed，是不可信输入：feed 可以把
 * <link> 写成 javascript:…、data:… 或相对 URL。渲染
 * <a href={…}> 前必须先经过本函数，只放行绝对 http: / https: URL。
 *
 * 不用当前 LumiRSS origin 补全相对 URL；正文内 sanitized <a> 的处理
 * 属于 DOMPurify URI policy，与本函数无关。
 */

/** 只允许绝对 http/https URL；malformed / 其它协议 / 相对 URL → null。 */
export function safeExternalHttpUrl(value: string | null): string | null {
  if (value === null) {
    return null
  }
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    // new URL 抛错 = malformed 或相对 URL（无 base 时不可解析）
    return null
  }
}
