/** clip-extract — 剪藏正文懒提取（phase2 Gate 3）。
 *
 * defuddle（主）/ @mozilla/readability（备）一律动态 import()：重依赖
 * 不进主 bundle，只在用户真正发起剪藏时按需加载。页面解析用浏览器
 * 原生 DOMParser（jsdom 是 dev-only 依赖，绝不进运行时）。
 *
 * 安全模型：提取出的 contentHtml 一律先过
 * lib/sanitize-article-html.ts（应用内唯一 DOMPurify 清洗点，与 Reader
 * 正文同一配置；scripts/styles/iframes/事件处理器由 DOMPurify 默认规则
 * 移除），随后在【已清洗】DOM 上做链接/图片协议白名单（http/https/
 * mailto / http/https/data）、相对 URL 绝对化与 rel=noopener noreferrer
 * ——对已清洗 DOM 的这些受控属性写入不引入任何不可信标记。
 * contentText 取自同一已清洗 DOM（textContent + 空白折叠）。
 * 本模块输出即 createClip 的存储 payload；渲染侧读取时还会再
 * sanitize 一次（双重边界）。 */

import { sanitizeArticleHtml } from './sanitize-article-html'

export interface ExtractedArticle {
  title: string
  byline: string | null
  contentHtml: string
  contentText: string
}

/** 两个提取器都失败（或都提取不到正文）时抛出；页面映射为固定文案
 * 「正文提取失败：可重试或只保存链接。」 */
export class ClipExtractError extends Error {
  constructor() {
    super('正文提取失败')
    this.name = 'ClipExtractError'
  }
}

function collapseWhitespace(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/** 这里只声明我们消费的字段（defuddle 的 DefuddleResponse 兼容此形状）。 */
interface DefuddleParseResult {
  title?: string
  author?: string
  content?: string
}

/** Readability.parse() 结果的已消费子集。 */
interface ReadabilityParseResult {
  title?: string
  byline?: string | null
  content?: string
}

/** 清洗 + 受控后处理，产出可存储 payload；无有效正文 → null
 * （交由下一个提取器兜底）。 */
function finalize(
  rawContentHtml: string,
  rawTitle: string,
  byline: string | null,
  baseUrl: string,
): ExtractedArticle | null {
  // 1) DOMPurify：最终安全边界（不允许 svg/mathml 命名空间，移除
  //    form/iframe/style 等 + inline style；on* 与 javascript: 由默认规则移除）
  const safeHtml = sanitizeArticleHtml(rawContentHtml)
  if (safeHtml.trim() === '') {
    return null
  }
  const doc = new DOMParser().parseFromString(safeHtml, 'text/html')

  // 2) 链接：只保留 http/https/mailto（相对 href 按 baseUrl 绝对化），
  //    并强制 rel=noopener noreferrer；malformed/越权协议 → 去掉链接
  //    语义、保留文字。
  for (const a of Array.from(doc.querySelectorAll('a[href]'))) {
    const href = a.getAttribute('href') ?? ''
    let nextHref: string | null = null
    try {
      const resolved = new URL(href, baseUrl)
      if (
        resolved.protocol === 'http:' ||
        resolved.protocol === 'https:' ||
        resolved.protocol === 'mailto:'
      ) {
        nextHref = resolved.href
      }
    } catch {
      // malformed href → nextHref 保持 null
    }
    if (nextHref === null) {
      a.removeAttribute('href')
    } else {
      a.setAttribute('href', nextHref)
      a.setAttribute('rel', 'noopener noreferrer')
    }
  }

  // 3) 图片：只保留 http/https/data（data:image 由 DOMPurify 默认对
  //    img 放行）；其余 → 去掉 src（alt 文字保留）。
  for (const img of Array.from(doc.querySelectorAll('img[src]'))) {
    const src = img.getAttribute('src') ?? ''
    if (/^data:image\//i.test(src)) {
      continue
    }
    try {
      const resolved = new URL(src, baseUrl)
      if (resolved.protocol === 'http:' || resolved.protocol === 'https:') {
        img.setAttribute('src', resolved.href)
        continue
      }
    } catch {
      // malformed src → 移除
    }
    img.removeAttribute('src')
  }

  const contentText = collapseWhitespace(doc.body.textContent ?? '')
  if (contentText === '') {
    return null
  }
  const title = collapseWhitespace(rawTitle)
  const bylineTrimmed = byline === null ? null : collapseWhitespace(byline)
  return {
    title: title !== '' ? title : baseUrl,
    byline: bylineTrimmed !== null && bylineTrimmed !== '' ? bylineTrimmed : null,
    contentHtml: doc.body.innerHTML,
    contentText,
  }
}

/** 从抓取到的页面 HTML 提取正文。主：defuddle；备：readability；
 * 两者都失败 → ClipExtractError。 */
export async function extractArticle(
  html: string,
  baseUrl: string,
): Promise<ExtractedArticle> {
  // defuddle 会原地修改传入的 Document（剥离 script 等），主/备提取器
  // 各自从原始 HTML 独立解析，互不污染。
  try {
    // 包入口仅 default 导出（CJS 互操作）。
    const Defuddle = (await import('defuddle')).default
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    // useAsync:false —— 禁止 defuddle 向第三方 API 发起额外请求
    //（提取只消费本次抓取的本地 HTML，不产生任何带外网络行为）。
    const result: DefuddleParseResult = new Defuddle(parsed, {
      url: baseUrl,
      useAsync: false,
    }).parse()
    const finalized =
      typeof result.content === 'string' && result.content.trim() !== ''
        ? finalize(result.content, result.title ?? '', result.author ?? null, baseUrl)
        : null
    if (finalized !== null) {
      return finalized
    }
  } catch {
    // defuddle 抛错或无正文 → readability 兜底
  }

  try {
    const { Readability } = await import('@mozilla/readability')
    const parsed = new DOMParser().parseFromString(html, 'text/html')
    const result = new Readability(parsed).parse() as ReadabilityParseResult | null
    const finalized =
      result !== null && typeof result.content === 'string' && result.content.trim() !== ''
        ? finalize(result.content, result.title ?? '', result.byline ?? null, baseUrl)
        : null
    if (finalized !== null) {
      return finalized
    }
  } catch {
    // 两个提取器都失败
  }

  throw new ClipExtractError()
}
