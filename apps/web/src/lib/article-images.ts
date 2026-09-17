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
