/** collect-article-links — F054 文中链接清单（净化后 DOM 收集）。
 *
 * - 收集 a[href]：绝对化（相对地址按文档 base 解析）、去重、按域名分组；
 * - 收集时即排除危险协议（javascript:/data:/vbscript:）——不出现、
 *   不可执行；「打开」仅 http/https（safe-external-http-url 复用）；
 * - Unicode 域名显示为 punycode（URL.host 天然 punycode 化）；
 * - 超长 URL 显示截断（完整地址可复制）。
 */

export interface ArticleLink {
  /** 绝对化后的目标地址 */
  href: string
  /** 链接文字（aria-hidden 图标链接退化为 host） */
  text: string
  /** 目标 host（punycode） */
  host: string
}

const SAFE_PROTOCOLS = new Set(['http:', 'https:'])

/** 从净化后的容器收集链接（已排除危险协议；保持出现顺序去重）。 */
export function collectArticleLinks(container: ParentNode): ArticleLink[] {
  const anchors = container.querySelectorAll('a[href]')
  const seen = new Set<string>()
  const links: ArticleLink[] = []
  anchors.forEach((node) => {
    if (!(node instanceof HTMLAnchorElement)) return
    const raw = node.getAttribute('href') ?? ''
    let resolved: URL
    try {
      resolved = new URL(raw, document.baseURI)
    } catch {
      return // 无法解析的地址（含 javascript: 等畸形）不出现
    }
    if (!SAFE_PROTOCOLS.has(resolved.protocol)) return // data:/vbscript:/javascript: 排除
    const href = resolved.toString()
    if (seen.has(href)) return
    seen.add(href)
    const text = (node.textContent ?? '').trim() || resolved.host
    links.push({ href, text, host: resolved.host })
  })
  return links
}

/** 按域名分组（保持组内出现顺序；host 为 punycode 显示）。 */
export function groupLinksByHost(links: ArticleLink[]): Map<string, ArticleLink[]> {
  const groups = new Map<string, ArticleLink[]>()
  for (const link of links) {
    const bucket = groups.get(link.host)
    if (bucket === undefined) groups.set(link.host, [link])
    else bucket.push(link)
  }
  return groups
}

/** 显示用截断（完整地址仍可复制）。 */
export function displayUrl(url: string, max = 72): string {
  return url.length <= max ? url : `${url.slice(0, max)}…`
}
