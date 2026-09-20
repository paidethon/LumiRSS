/** F009 远程图片隐私加载 —— 「默认不加载远程图片」的客户端保证。
 *
 * 与 F22（readerImageMode='hidden'，全篇 defer + 单篇恢复）互补：
 * 本模块只处理「远程 http(s) 图片」——启用后 img 的远程 src 被替换为
 * 受控占位按钮（原地址存 data-lumi-blocked-src，不发生网络请求）；
 * 相对路径 / /api/v1/*（快照本地资源）/ data: / blob: 不受影响。
 * 点击占位「加载本图」→ 该 URL 进入本次会话例外集合（刷新后恢复
 * 默认拦截态；例外是会话内记忆，不持久化）。
 *
 * 安全：输入/输出都已是 DOMPurify 清洗后的 HTML；占位按钮由 DOM API
 * 构造（createElement + textContent + setAttribute），不引入注入面。 */

const STORAGE_KEY = 'lumirss-block-remote-images'

/** 读取设置（corrupted / 缺失 → false = 默认加载）。 */
export function readBlockRemoteImages(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): boolean {
  if (storage === null) return false
  try {
    return storage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function writeBlockRemoteImages(
  value: boolean,
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    // 写失败静默：设备本地偏好
  }
}

// ---- 会话内例外集合（不持久化；刷新后恢复默认拦截态） ----

const sessionAllowed = new Set<string>()

/** 允许该远程图片在本次会话内加载（单图粒度例外）。 */
export function allowRemoteImage(url: string): void {
  if (url !== '') sessionAllowed.add(url)
}

export function isRemoteImageAllowed(url: string): boolean {
  return sessionAllowed.has(url)
}

/** 测试用：清空会话例外。 */
export function clearRemoteImageExceptions(): void {
  sessionAllowed.clear()
}

/** 远程 http(s) 绝对 URL（有 hostname）→ true；相对路径、协议相对、
 * data:/blob:、/api/v1/* 等本地资源 → false。 */
export function isRemoteHttpUrl(url: string): boolean {
  if (typeof url !== 'string') return false
  const trimmed = url.trim()
  if (!/^https?:\/\//i.test(trimmed)) return false
  try {
    const parsed = new URL(trimmed)
    return parsed.hostname !== ''
  } catch {
    return false
  }
}

export interface BlockedImages {
  html: string
  blockedCount: number
}

/** 把远程 img 替换为受控占位按钮（原地址存 data-lumi-blocked-src，
 * 摘除 src/srcset → 不发请求）。会话例外中的 URL 原样保留。 */
export function blockRemoteImages(html: string): BlockedImages {
  if (typeof window === 'undefined' || !html.includes('<img')) {
    return { html, blockedCount: 0 }
  }
  const doc = new DOMParser().parseFromString(html, 'text/html')
  let blocked = 0
  for (const img of Array.from(doc.querySelectorAll('img'))) {
    const src = img.getAttribute('src')
    if (src === null || !isRemoteHttpUrl(src) || isRemoteImageAllowed(src)) continue
    // 属性级替换（受控）：保留占位与原地址，摘除一切会触发加载的属性
    img.setAttribute('data-lumi-blocked-src', src)
    img.removeAttribute('src')
    const srcset = img.getAttribute('srcset')
    if (srcset !== null) img.removeAttribute('srcset')
    img.setAttribute('data-lumi-image', 'blocked')
    blocked += 1
  }
  return { html: doc.body.innerHTML, blockedCount: blocked }
}

/** 恢复单个被拦截的 img（「加载本图」按钮点击后由调用方触发）。
 * 直接在 live DOM 上操作：记录例外 → 还原 src → 清理占位属性。 */
export function unblockSingleImage(img: HTMLImageElement): void {
  const src = img.getAttribute('data-lumi-blocked-src')
  if (src === null) return
  allowRemoteImage(src)
  img.setAttribute('src', src)
  img.removeAttribute('data-lumi-blocked-src')
  img.removeAttribute('data-lumi-image')
}


/** 渲染后装饰（幂等，decorateCodeCopyButtons 同一模式）：把占位 img
 * 换成可点击的「加载本图」按钮；点击 = 记录会话例外 + 还原真实 img。 */
export function decorateBlockedRemoteImages(container: HTMLElement): void {
  for (const img of Array.from(
    container.querySelectorAll('img[data-lumi-image="blocked"]'),
  )) {
    const src = img.getAttribute('data-lumi-blocked-src')
    if (src === null) continue
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'lumi-blocked-image'
    button.setAttribute('data-lumi-blocked-src', src)
    button.textContent = '加载本图'
    button.setAttribute('aria-label', '加载本图（远程图片默认已拦截）')
    img.replaceWith(button)
    button.addEventListener('click', () => {
      allowRemoteImage(src)
      const restored = document.createElement('img')
      restored.setAttribute('src', src)
      button.replaceWith(restored)
    })
  }
}
