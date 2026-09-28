/** content-links — FIX-137 正文链接的打开方式与安全属性。
 *
 * 正文 <a href> 来自不可信 RSS（sanitize 只兜安全底线，不管打开行为）。
 * 本模块给净化后的链接做统一分类与装饰，让行为可预测：
 * - `#…` 纯 hash 锚     → anchor：页内滚动（FIX-267 拦截器负责，不装饰）；
 * - 同源 http(s) 链接   → app：拦截默认导航，navigateToPath 应用内路由
 *                         （不在本页丢状态整页跳转）；
 * - 跨源 http(s) 链接   → external：装饰 target=_blank +
 *                         rel="noopener noreferrer"（中键/辅助键行为由
 *                         浏览器按装饰属性处理），左键点击统一走
 *                         window.open(url, '_blank', 'noopener,noreferrer')
 *                         （与 lib/open-item 同一口径）；
 * - mailto:/tel: 等     → passive：浏览器默认行为安全且有语义，不拦截
 *                         不装饰；
 * - javascript:/data:/vbscript:/file:/blob: 与解析失败 → unsafe：
 *                         preventDefault（DOMPurify 已剥离危险 href，
 *                         这里是纵深防御：万一漏网也绝不执行/导航）。
 *
 * 相对地址按 base 解析（调用方传 detail.url，与 FIX-263 媒体绝对化
 * 同一基准）——文章站相对链接 → external 新标签，而不是被误当应用内
 * 路由整页跳走。
 */

import { navigateToPath } from './app-route'

export type ContentLinkKind = 'anchor' | 'app' | 'external' | 'passive' | 'unsafe'

export interface ContentLinkClassification {
  kind: ContentLinkKind
  /** external：绝对化后的完整地址。 */
  href: string | null
  /** app：目标应用内路径（pathname + search + hash）。 */
  appPath: string | null
}

const ANCHOR_KIND = { kind: 'anchor' as const, href: null, appPath: null }
const PASSIVE_KIND = { kind: 'passive' as const, href: null, appPath: null }

function unsafeKind(): ContentLinkClassification {
  return { kind: 'unsafe', href: null, appPath: null }
}

/** 点击分类结果的可执行动作（纯判定与副作用分离，便于单测）。
 * 返回 true 表示点击已被接管（调用方无需再做默认行为）。 */
export function openContentLink(
  classification: ContentLinkClassification,
  deps: {
    openExternal?: (url: string) => void
    navigateApp?: (path: string) => void
  } = {},
): boolean {
  switch (classification.kind) {
    case 'external': {
      if (classification.href === null) return false
      const open = deps.openExternal ?? ((url: string) =>
        window.open(url, '_blank', 'noopener,noreferrer'))
      open(classification.href)
      return true
    }
    case 'app': {
      if (classification.appPath === null) return false
      const navigate = deps.navigateApp ?? navigateToPath
      navigate(classification.appPath)
      return true
    }
    case 'unsafe':
      // 纵深防御：危险协议绝不执行，也绝不导航。
      return true
    case 'anchor':
    case 'passive':
    default:
      return false
  }
}

/** 分类一条正文链接 href（raw 原样，未绝对化）。 */
export function classifyContentLink(
  rawHref: string,
  base: string,
  appOrigin: string = typeof window !== 'undefined' ? window.location.origin : '',
): ContentLinkClassification {
  if (rawHref.startsWith('#')) return ANCHOR_KIND
  let resolved: URL
  try {
    resolved = new URL(rawHref, base)
  } catch {
    return unsafeKind()
  }
  if (resolved.protocol === 'http:' || resolved.protocol === 'https:') {
    if (resolved.origin === appOrigin && appOrigin !== '') {
      return {
        kind: 'app',
        href: resolved.href,
        appPath: `${resolved.pathname}${resolved.search}${resolved.hash}`,
      }
    }
    return { kind: 'external', href: resolved.href, appPath: null }
  }
  if (
    resolved.protocol === 'javascript:' ||
    resolved.protocol === 'data:' ||
    resolved.protocol === 'vbscript:' ||
    resolved.protocol === 'file:' ||
    resolved.protocol === 'blob:'
  ) {
    return unsafeKind()
  }
  // mailto:/tel:/ftp: 等：默认行为交给浏览器（安全且语义明确）。
  return PASSIVE_KIND
}

/** 渲染后装饰（幂等）：external 补 target/rel；其余链接不留新标签
 * 语义。每次 html 重跑管线后重装饰，随 dangerouslySetInnerHTML 重设
 * 自动重来。 */
export function decorateContentLinks(container: HTMLElement, base: string): void {
  for (const anchor of Array.from(container.querySelectorAll('a[href]'))) {
    if (!(anchor instanceof HTMLAnchorElement)) continue
    const raw = anchor.getAttribute('href') ?? ''
    const kind = classifyContentLink(raw, base).kind
    if (kind === 'external') {
      anchor.setAttribute('target', '_blank')
      anchor.setAttribute('rel', 'noopener noreferrer')
    } else {
      anchor.removeAttribute('target')
      anchor.removeAttribute('rel')
    }
  }
}
