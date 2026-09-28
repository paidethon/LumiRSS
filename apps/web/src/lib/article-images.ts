/** 省流图片治理（F22）——「禁图状态不发图片请求」的客户端保证。
 *
 * 背景：readerImageMode='hidden' 最初只用 CSS display:none 隐藏 <img>，
 * 浏览器仍会完整下载图片——省流语义不成立。本模块在 HTML 进入 DOM
 * **之前**把 src/srcset 摘掉（保存进 data-*），图片请求根本不发生；
 * 用户对单篇文章点「加载图片」时才恢复真实地址。
 *
 * 安全：输入/输出都已是 DOMPurify 清洗后的 HTML；本模块只读写 img 的
 * src/srcset/class/data-* 属性，不引入任何新的注入面（属性值经
 * setAttribute 写回，与 DOMParser 的 inert 解析一致）。 */

export interface DeferredImages {
  html: string
  imageCount: number
}

/** 摘除 img 的 src/srcset（存入 data-lumi-src / data-lumi-srcset）。
 * 已是 deferred 状态的 img 跳过（幂等）。 */
export function deferImages(html: string): DeferredImages {
  if (typeof window === 'undefined' || !html.includes('<img')) {
    return { html, imageCount: 0 }
  }
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const images = Array.from(doc.querySelectorAll('img'))
  let count = 0
  for (const img of images) {
    const src = img.getAttribute('src')
    const srcset = img.getAttribute('srcset')
    if (!src && !srcset) continue
    if (src) {
      img.setAttribute('data-lumi-src', src)
      img.removeAttribute('src')
    }
    if (srcset) {
      img.setAttribute('data-lumi-srcset', srcset)
      img.removeAttribute('srcset')
    }
    img.setAttribute('data-lumi-image', 'deferred')
    count += 1
  }
  return { html: doc.body.innerHTML, imageCount: count }
}

/** 恢复 deferred img 的真实地址（单篇「加载图片」覆盖动作）。 */
export function restoreImages(html: string): string {
  if (typeof window === 'undefined' || !html.includes('data-lumi-image')) return html
  const doc = new DOMParser().parseFromString(html, 'text/html')
  for (const img of Array.from(doc.querySelectorAll('img[data-lumi-image="deferred"]'))) {
    const src = img.getAttribute('data-lumi-src')
    const srcset = img.getAttribute('data-lumi-srcset')
    if (src) img.setAttribute('src', src)
    if (srcset) img.setAttribute('srcset', srcset)
    img.removeAttribute('data-lumi-image')
    img.removeAttribute('data-lumi-src')
    img.removeAttribute('data-lumi-srcset')
  }
  return doc.body.innerHTML
}

// ---- FIX-263：相对媒体地址按文章原站解析 ----
//
// 正文 HTML 是原站文章页的搬运件，src/srcset 里的相对地址语义属于
// 原站；直接进 DOM 会被浏览器按【应用源】解析 → 请求打到 LumiRSS
// 自身 → 404。渲染进 DOM 前把每个候选按文章原站 URL 绝对化（与原站
// 浏览器按文档 URL 解析的语义一致）。安全：输入已是 DOMPurify 输出，
// 本模块只读写 img 的 src/srcset 属性（setAttribute），解析结果只放行
// http(s)，不引入注入面。

/** 无 scheme 且非纯文内锚点的地址才需要按 base 解析；带 scheme 的
 * （http(s):、data:、blob:、mailto: 等）原样保留。协议相对
 * （//host/x）无 scheme → 参与解析（继承 base 的 scheme）。 */
function needsBaseResolution(raw: string): boolean {
  if (raw === '' || raw.startsWith('#')) return false
  return !/^[a-z][a-z0-9+.-]*:/i.test(raw)
}

/** 应用本地资源（/api/*，快照图片通道）必须留在应用源——按原站解析
 * 会指向外站 404（与 F009「/api/v1/* 快照本地资源不受影响」同语义）。 */
function isAppLocalPath(raw: string): boolean {
  return raw.startsWith('/api/')
}

function resolveCandidate(url: string, base: URL): string | null {
  if (!needsBaseResolution(url) || isAppLocalPath(url)) return null
  try {
    const resolved = new URL(url, base)
    // 只回写 http(s)（相对地址解析不出其它协议，防御性兜底）。
    if (resolved.protocol !== 'http:' && resolved.protocol !== 'https:') return null
    return resolved.toString()
  } catch {
    return null
  }
}

/** srcset 按 HTML 规范以逗号分候选（候选 URL 内不允许字面逗号，需
 * 百分号编码）；每候选 = URL + 可选描述符，只解析 URL 部分。任何
 * 候选都没变 → 返回 null（不回写，未触及的属性逐字保持原样）；
 * 有变更时整体以规范形态（候选间「, 」）重建。 */
function resolveSrcset(srcset: string, base: URL): string | null {
  let changed = false
  const resolved = srcset.split(',').map((part) => {
    const trimmed = part.trim()
    if (trimmed === '') return null
    const tokens = trimmed.split(/\s+/)
    const target = resolveCandidate(tokens[0]!, base)
    if (target === null) return trimmed
    changed = true
    return [target, ...tokens.slice(1)].join(' ')
  })
  if (!changed) return null
  return resolved.filter((part): part is string => part !== null).join(', ')
}

export interface ResolvedMedia {
  html: string
  /** 地址被改写的 img 数（同一 img 的 src+srcset 都改只计 1）。 */
  resolvedCount: number
}

/** 把 img 的相对 src / srcset 候选按 baseUrl（文章原站 URL）绝对化。
 * baseUrl 缺失/非法/非 http(s) 或正文无 <img → 原样返回。 */
export function resolveRelativeMedia(
  html: string,
  baseUrl: string | null | undefined,
): ResolvedMedia {
  if (typeof window === 'undefined' || !html.includes('<img')) {
    return { html, resolvedCount: 0 }
  }
  let base: URL
  try {
    base = new URL(baseUrl ?? '')
  } catch {
    return { html, resolvedCount: 0 }
  }
  if (base.protocol !== 'http:' && base.protocol !== 'https:') {
    return { html, resolvedCount: 0 }
  }
  const doc = new DOMParser().parseFromString(html, 'text/html')
  let count = 0
  for (const img of Array.from(doc.querySelectorAll('img'))) {
    let touched = false
    const src = img.getAttribute('src')
    if (src !== null) {
      const resolved = resolveCandidate(src.trim(), base)
      if (resolved !== null) {
        img.setAttribute('src', resolved)
        touched = true
      }
    }
    const srcset = img.getAttribute('srcset')
    if (srcset !== null) {
      const resolved = resolveSrcset(srcset, base)
      if (resolved !== null) {
        img.setAttribute('srcset', resolved)
        touched = true
      }
    }
    if (touched) count += 1
  }
  return { html: doc.body.innerHTML, resolvedCount: count }
}
