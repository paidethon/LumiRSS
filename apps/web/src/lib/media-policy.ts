/** media-policy — N066 媒体仅手动加载（按源，设备本地）。
 *
 * BFF source_overrides 没有 mediaPolicy 字段（已核实 2026-09），本特性
 * 保持设备本地：localStorage `lumirss-media-policy` 存 {feedUrl: mode}
 * 映射，mode = 'default'（跟随既有图片策略）| 'manual'（图片+视频+音频
 * 一律先占位，点击才加载单个元素）。
 *
 * 「仅手动」的客户端保证与 F22/F009 同族：HTML 进 DOM **之前**摘除一切
 * 会触发请求的属性（img src/srcset、video/audio src、video poster、
 * source src/srcset、track src）——初始渲染零外部媒体请求；渲染后装饰
 * 把占位换成「加载」按钮，点击只恢复该一个元素。
 *
 * 安全：输入/输出都已是 DOMPurify 清洗后的 HTML；本模块只读写受控属性
 * （setAttribute/removeAttribute），占位按钮由 DOM API 构造，不引入
 * 注入面。 */

export const MEDIA_POLICY_STORAGE_KEY = 'lumirss-media-policy'

export type MediaPolicyMode = 'default' | 'manual'

export const MEDIA_POLICY_MODES: readonly MediaPolicyMode[] = ['default', 'manual']

/** 读取整个映射（corrupted → {}，诚实回退默认）。 */
export function readMediaPolicies(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): Record<string, MediaPolicyMode> {
  if (storage === null) return {}
  try {
    const raw = storage.getItem(MEDIA_POLICY_STORAGE_KEY)
    if (raw === null) return {}
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: Record<string, MediaPolicyMode> = {}
    for (const [feedUrl, mode] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof feedUrl !== 'string' || feedUrl === '') continue
      if (MEDIA_POLICY_MODES.includes(mode as MediaPolicyMode)) {
        out[feedUrl] = mode as MediaPolicyMode
      }
    }
    return out
  } catch {
    return {}
  }
}

/** 写入单个源的策略（mode = 'default' 时移除该键，保持映射紧凑）。 */
export function writeMediaPolicy(
  feedUrl: string,
  mode: MediaPolicyMode,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null || feedUrl === '') return
  try {
    const map = readMediaPolicies(storage)
    if (mode === 'default') delete map[feedUrl]
    else map[feedUrl] = mode
    storage.setItem(MEDIA_POLICY_STORAGE_KEY, JSON.stringify(map))
  } catch {
    // 写失败静默：设备本地偏好
  }
}

/** 查询某源策略（未知/缺失 → 'default'）。 */
export function mediaPolicyFor(
  feedUrl: string | null | undefined,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): MediaPolicyMode {
  if (feedUrl === null || feedUrl === undefined || feedUrl === '') return 'default'
  return readMediaPolicies(storage)[feedUrl] ?? 'default'
}

// ---- HTML 变换（进入 DOM 前） ----

export interface DeferredMedia {
  html: string
  /** 摘除的媒体元素数（img/video/audio；source/track 随宿主不重复计数）。 */
  mediaCount: number
}

const MEDIA_HOST_SELECTOR = 'img, video, audio'
const MEDIA_ATTR_SELECTOR = 'video, audio, source, track'

/** 「仅手动」变换：把 img/video/audio 的加载属性摘除存进 data-*，并打
 * data-lumi-media="deferred" 标记。已是 deferred / 已被 F22 defer 的
 * img（无 src 可摘）自然跳过（幂等）。 */
export function deferMedia(html: string): DeferredMedia {
  if (typeof window === 'undefined' || !/<(img|video|audio)\b/i.test(html)) {
    return { html, mediaCount: 0 }
  }
  const doc = new DOMParser().parseFromString(html, 'text/html')
  let count = 0
  for (const host of Array.from(doc.querySelectorAll(MEDIA_HOST_SELECTOR))) {
    // 已标记（重入）→ 跳过
    if (host.getAttribute('data-lumi-media') === 'deferred') continue
    let touched = false
    const move = (attr: string, data: string): void => {
      const value = host.getAttribute(attr)
      if (value !== null) {
        host.setAttribute(data, value)
        host.removeAttribute(attr)
        touched = true
      }
    }
    move('src', 'data-lumi-media-src')
    move('poster', 'data-lumi-media-poster')
    if (host.tagName === 'IMG') {
      move('srcset', 'data-lumi-media-srcset')
    }
    // 宿主内部的 source/track 也一并摘除（否则 <video><source></video>
    // 的 source 仍会触发请求）
    for (const child of Array.from(host.querySelectorAll(MEDIA_ATTR_SELECTOR))) {
      const childSrc = child.getAttribute('src')
      if (childSrc !== null) {
        child.setAttribute('data-lumi-media-src', childSrc)
        child.removeAttribute('src')
        touched = true
      }
      const childSrcset = child.getAttribute('srcset')
      if (childSrcset !== null) {
        child.setAttribute('data-lumi-media-srcset', childSrcset)
        child.removeAttribute('srcset')
        touched = true
      }
    }
    if (touched) {
      host.setAttribute('data-lumi-media', 'deferred')
      count += 1
    }
  }
  return { html: doc.body.innerHTML, mediaCount: count }
}

// ---- 渲染后装饰（占位 + 单元素加载） ----

function mediaKindLabel(el: Element): string {
  if (el.tagName === 'IMG') return '图片'
  if (el.tagName === 'VIDEO') return '视频'
  if (el.tagName === 'AUDIO') return '音频'
  return '媒体'
}

/** 恢复单个 deferred 媒体元素（点击占位后由调用方触发）：把保存的
 * src/srcset/poster 写回该元素（宿主与内部 source/track），只加载这一个。 */
export function restoreSingleMedia(host: Element): void {
  const restore = (el: Element): void => {
    const src = el.getAttribute('data-lumi-media-src')
    if (src !== null) {
      el.setAttribute('src', src)
      el.removeAttribute('data-lumi-media-src')
    }
    const srcset = el.getAttribute('data-lumi-media-srcset')
    if (srcset !== null) {
      el.setAttribute('srcset', srcset)
      el.removeAttribute('data-lumi-media-srcset')
    }
    const poster = el.getAttribute('data-lumi-media-poster')
    if (poster !== null) {
      el.setAttribute('poster', poster)
      el.removeAttribute('data-lumi-media-poster')
    }
  }
  restore(host)
  for (const child of Array.from(host.querySelectorAll(MEDIA_ATTR_SELECTOR))) restore(child)
  host.removeAttribute('data-lumi-media')
}

/** 渲染后装饰（幂等，decorateBlockedRemoteImages 同一模式）：把 deferred
 * 媒体元素替换为「加载图片/视频/音频」占位按钮；点击恢复仅该一个元素
 * （真实元素带原地址重新入 DOM，浏览器此时才发请求）。 */
export function decorateManualMedia(container: HTMLElement): number {
  let decorated = 0
  for (const host of Array.from(
    container.querySelectorAll('[data-lumi-media="deferred"]'),
  )) {
    const label = mediaKindLabel(host)
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'lumi-manual-media'
    button.textContent = `加载${label}`
    button.setAttribute('aria-label', `加载${label}（本源媒体仅手动加载）`)
    host.replaceWith(button)
    button.addEventListener('click', () => {
      restoreSingleMedia(host)
      button.replaceWith(host)
    })
    decorated += 1
  }
  return decorated
}
