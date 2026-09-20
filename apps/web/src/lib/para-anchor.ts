/** F015 段落定位链接 —— 稳定段落 id、链接构造/解析、登录前暂存恢复。
 *
 * - 段落 id = 内容哈希前 8 位 + 段序（正文不变则稳定；正文变化 =
 *   id 变化 → 定位失败时诚实提示，不跳错段）；
 * - 链接形如 `${origin}/?entry=<ref>&para=<id>`——绝不携带任何
 *   token / 凭据参数；
 * - 未登录打开链接 → 目标暂存 sessionStorage，登录后重放；
 *   已登录 → 直接打开文章（滚动 + 2.5s 高亮由 ArticleContent 消费）。 */

const PENDING_KEY = 'lumirss-pending-para'

/** FNV-1a 32 位哈希 → 8 位 hex（内容指纹，非加密）。 */
export function hash8(text: string): string {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/** 段落稳定 id：hash8(正文) + 段序。 */
export function paraStableId(text: string, index: number): string {
  return `${hash8(text)}-${index}`
}

/** 构造段落链接（origin 无尾斜杠；仅 entry/para 两个参数，无凭据）。 */
export function buildParaLink(origin: string, entryRef: string, paraId: string): string {
  const cleanOrigin = origin.endsWith('/') ? origin.slice(0, -1) : origin
  return `${cleanOrigin}/?entry=${encodeURIComponent(entryRef)}&para=${encodeURIComponent(paraId)}`
}

export interface ParaTarget {
  entry: string
  para: string
}

/** 从 location.search 解析 ?entry=&para=（二者齐全才有效）。 */
export function parseParaParams(search: string): ParaTarget | null {
  try {
    const params = new URLSearchParams(search)
    const entry = params.get('entry')
    const para = params.get('para')
    if (entry !== null && para !== null && entry !== '' && para !== '') {
      return { entry, para }
    }
  } catch {
    return null
  }
  return null
}

/** 暂存登录前目标（sessionStorage；读取即清除）。 */
export function stashPendingPara(target: ParaTarget): void {
  try {
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(target))
  } catch {
    // 暂存失败 = 放弃恢复（不阻塞启动）
  }
}

/** 读取并清除暂存目标。 */
export function takePendingPara(): ParaTarget | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY)
    if (raw === null) return null
    sessionStorage.removeItem(PENDING_KEY)
    const parsed: unknown = JSON.parse(raw)
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      typeof (parsed as ParaTarget).entry === 'string' &&
      typeof (parsed as ParaTarget).para === 'string'
    ) {
      return parsed as ParaTarget
    }
  } catch {
    return null
  }
  return null
}

/**
 * App 启动钩子：解析 URL 中的段落目标。
 * - 已登录 → 立即打开文章（保留 para 在 sessionStorage 供
 *   ArticleContent 渲染后消费：滚动 + 高亮 / 诚实提示）；
 * - 未登录 → 暂存，登录后由 tryResumePendingPara 重放。
 * 无论哪种情况都把 query 从地址栏清除（不把目标留在分享/书签外）。
 */
export function initParaTarget(
  isAuthed: () => boolean,
  openEntry: (entryRef: string) => void,
): void {
  let target: ParaTarget | null = null
  try {
    target = parseParaParams(window.location.search)
    if (target === null) return
    const params = new URLSearchParams(window.location.search)
    params.delete('entry')
    params.delete('para')
    const rest = params.toString()
    window.history.replaceState(
      null,
      '',
      `${window.location.origin}${window.location.pathname}${rest ? `?${rest}` : ''}`,
    )
  } catch {
    return
  }
  if (isAuthed()) {
    try {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(target))
    } catch {
      // 忽略：ArticleContent 消费不到就不高亮
    }
    openEntry(target.entry)
  } else {
    stashPendingPara(target)
  }
}

/** 登录完成后重放暂存目标（已登录时由 App 在状态翻转处调用）。 */
export function tryResumePendingPara(openEntry: (entryRef: string) => void): void {
  const target = takePendingPara()
  if (target !== null) {
    try {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(target))
    } catch {
      // 忽略
    }
    openEntry(target.entry)
  }
}

/** ArticleContent 渲染后消费：取回与本条目匹配的目标（读取即清除）。 */
export function takeParaTargetForEntry(entryRef: string): string | null {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY)
    if (raw === null) return null
    sessionStorage.removeItem(PENDING_KEY)
    const parsed: unknown = JSON.parse(raw)
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      (parsed as ParaTarget).entry === entryRef
    ) {
      return (parsed as ParaTarget).para
    }
  } catch {
    return null
  }
  return null
}
