/** attachment-queue — N065 附件下载队列（设备本地，纯逻辑核心）。
 *
 * 语义：
 * - 白名单：按扩展名 / MIME 判定「可下载附件」——音频/视频/图片/PDF/EPUB
 *   放行，脚本与可执行文件（js/exe/sh/bat/msi/apk/…）及一切白名单外类型
 *   拒绝（白名单制，天然拒绝未知格式）；
 * - 队列元数据存 localStorage（`lumirss-attachment-queue`），只存元数据
 *   （名称/大小/进度/状态），二进制从不落 localStorage；
 * - 磁盘上限 200MB（按元数据估算）：新条目放不进去时按加入时间最旧优先
 *   逐出已完成/失败条目（LRU 语义），并如实返回逐出清单——面板给诚实
 *   提示，不悄悄丢弃；
 * - 文件名净化：剥路径分隔符/控制字符，保留 CJK，防点开头/尾与保留名；
 * - 下载执行：fetch → ReadableStream reader 逐块累计（有 Content-Length
 *   时报告进度）→ Blob → object URL → anchor 下载；无流式 body 的环境
 *   （jsdom/旧浏览器）诚实退化为整体 blob()，进度为 0→100 两跳。
 *
 * 安全：绝不保存脚本类文件（白名单先行）；下载动作由浏览器 anchor +
 * download 属性承担，不经任何 eval/注入面。 */

export const ATTACHMENT_QUEUE_STORAGE_KEY = 'lumirss-attachment-queue'

/** 磁盘上限（200MB；元数据口径——如实提示，不假装精确的磁盘审计）。 */
export const ATTACHMENT_QUEUE_CAP_BYTES = 200 * 1024 * 1024

/** 扩展名白名单（小写；不含点）。脚本/可执行文件不在表内 = 拒绝。 */
export const ALLOWED_ATTACHMENT_EXTENSIONS = [
  // 音频
  'mp3', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'wav', 'flac',
  // 视频
  'mp4', 'm4v', 'webm', 'mov',
  // 文档
  'pdf', 'epub',
  // 图片
  'jpg', 'jpeg', 'png', 'gif', 'webp',
] as const

/** MIME 白名单前缀/全集（type 缺失时按扩展名兜底；两者都缺失 = 拒绝）。 */
const ALLOWED_MIME_PREFIXES = ['audio/', 'video/', 'image/'] as const
const ALLOWED_MIME_EXACT = ['application/pdf', 'application/epub+zip'] as const

/** 显式拒绝表（即使伪称了白名单 MIME 也拒绝——扩展名胜出）。 */
const DENIED_EXTENSIONS = new Set([
  'js', 'mjs', 'cjs', 'exe', 'msi', 'bat', 'cmd', 'com', 'scr', 'ps1',
  'sh', 'bash', 'zsh', 'apk', 'jar', 'dll', 'so', 'dylib', 'htm', 'html',
  'xhtml', 'svg', 'php', 'jsp', 'asp', 'aspx', 'vbs', 'wsf', 'hta',
])

/** 取 URL/文件名的扩展名（小写、无点；无 → ''）。剥离查询串。 */
export function attachmentExtension(urlOrName: string): string {
  if (typeof urlOrName !== 'string') return ''
  const path = urlOrName.split(/[?#]/)[0] ?? ''
  const base = path.split(/[/\\]/).pop() ?? ''
  const dot = base.lastIndexOf('.')
  if (dot <= 0 || dot === base.length - 1) return ''
  return base.slice(dot + 1).toLowerCase()
}

/** 白名单判定：扩展名在白名单且不在拒绝表；或 MIME 命中白名单且扩展名
 * 不在拒绝表。两者都取不到 → 拒绝（不猜）。 */
export function isAllowedAttachment(href: string, mime?: string | null): boolean {
  const ext = attachmentExtension(href)
  if (DENIED_EXTENSIONS.has(ext)) return false
  if ((ALLOWED_ATTACHMENT_EXTENSIONS as readonly string[]).includes(ext)) return true
  const normalizedMime = ((mime ?? '') as string).toLowerCase().split(';')[0]?.trim() ?? ''
  if (normalizedMime === '') return false
  if ((ALLOWED_MIME_EXACT as readonly string[]).includes(normalizedMime)) return true
  return ALLOWED_MIME_PREFIXES.some((prefix) => normalizedMime.startsWith(prefix))
}

/** 文件名净化：剥路径分隔符与控制字符，保留 CJK/字母/数字/常用安全符；
 * 防空名、防纯点、长度钳制（120）。fallback 兜底（默认 'attachment'）。 */
export function sanitizeAttachmentFilename(name: string, fallback = 'attachment'): string {
  const raw = typeof name === 'string' ? name : ''
  // 控制字符逐一剔除（避免正则控制字符区间）
  const withoutControl = Array.from(raw)
    .filter((ch) => ch.charCodeAt(0) > 0x1f)
    .join('')
  const stripped = withoutControl.replace(/[/\\:*?"<>|]/g, '').trim()
  // 纯点（.. / .）或空 → fallback
  const base = /^\.+$/.test(stripped) || stripped === '' ? fallback : stripped
  return base.slice(0, 120)
}

/** 从 enclosure URL 派生净化后的文件名。 */
export function attachmentFilenameFromUrl(url: string, fallback = 'attachment'): string {
  const path = url.split(/[?#]/)[0] ?? ''
  const base = path.split(/[/\\]/).pop() ?? ''
  return sanitizeAttachmentFilename(decodeURIComponentSafely(base), fallback)
}

function decodeURIComponentSafely(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

// ---- 队列元数据（localStorage，设备本地） ----

export type AttachmentStatus = 'queued' | 'downloading' | 'done' | 'failed' | 'canceled'

export interface AttachmentQueueItem {
  id: string
  url: string
  /** 净化后的文件名。 */
  name: string
  /** 已知大小（bytes）；未知 = null（诚实显示「大小未知」）。 */
  size: number | null
  status: AttachmentStatus
  /** 0–100；未知总大小时进度不可信（保持 0，以 loaded 字节说明）。 */
  progress: number
  /** 已接收字节（总大小未知时的诚实进度口径）。 */
  loaded: number
  /** 失败原因（诚实透出；成功为 null）。 */
  error: string | null
  addedAt: number
  /** 已重试次数（retry-once：≥1 后不再允许重试）。 */
  retries: number
}

/** 不可信 JSON → 合法队列（逐条校验；url/name 缺失丢弃；重复 url 去重）。 */
export function normalizeAttachmentQueue(raw: unknown): AttachmentQueueItem[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: AttachmentQueueItem[] = []
  const STATUSES: readonly AttachmentStatus[] = ['queued', 'downloading', 'done', 'failed', 'canceled']
  for (const item of raw) {
    if (typeof item !== 'object' || item === null) continue
    const r = item as Record<string, unknown>
    if (typeof r.url !== 'string' || r.url === '') continue
    if (typeof r.name !== 'string' || r.name === '') continue
    if (seen.has(r.url)) continue
    seen.add(r.url)
    const status = STATUSES.includes(r.status as AttachmentStatus)
      ? (r.status as AttachmentStatus)
      : 'failed'
    out.push({
      id: typeof r.id === 'string' && r.id !== '' ? r.id : `att-${String(r.addedAt ?? 0)}`,
      url: r.url,
      name: sanitizeAttachmentFilename(r.name),
      size:
        typeof r.size === 'number' && Number.isFinite(r.size) && r.size >= 0
          ? r.size
          : null,
      status,
      progress:
        typeof r.progress === 'number' && Number.isFinite(r.progress)
          ? Math.min(100, Math.max(0, r.progress))
          : 0,
      loaded:
        typeof r.loaded === 'number' && Number.isFinite(r.loaded) && r.loaded >= 0
          ? r.loaded
          : 0,
      error: typeof r.error === 'string' ? r.error : null,
      addedAt: typeof r.addedAt === 'number' && Number.isFinite(r.addedAt) ? r.addedAt : 0,
      retries: typeof r.retries === 'number' && Number.isFinite(r.retries) && r.retries >= 0
        ? Math.floor(r.retries)
        : 0,
    })
  }
  return out
}

export function readAttachmentQueue(
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): AttachmentQueueItem[] {
  if (storage === null) return []
  try {
    const raw = storage.getItem(ATTACHMENT_QUEUE_STORAGE_KEY)
    if (raw === null) return []
    return normalizeAttachmentQueue(JSON.parse(raw))
  } catch {
    return []
  }
}

export function writeAttachmentQueue(
  items: AttachmentQueueItem[],
  storage: Storage | null = typeof localStorage === 'undefined' ? null : localStorage,
): void {
  if (storage === null) return
  try {
    storage.setItem(ATTACHMENT_QUEUE_STORAGE_KEY, JSON.stringify(items))
  } catch {
    // 元数据写失败静默：会话内状态仍在
  }
}

// ---- 容量规划（LRU 逐出，返回诚实清单） ----

export interface CapacityPlan {
  /** 逐出后保留的条目（不含新条目）。 */
  kept: AttachmentQueueItem[]
  /** 因容量被逐出的条目（面板逐条诚实提示）。 */
  evicted: AttachmentQueueItem[]
  /** 新条目本身超限 → 拒绝加入。 */
  overCap: boolean
}

function bytesOf(item: AttachmentQueueItem): number {
  return item.size ?? 0
}

/** 规划加入 incomingBytes 后的队列：先逐出最旧的 done/failed/canceled，
 * 仍不够再逐出最旧的 queued/downloading（LRU 近似——最旧优先）。单个
 * 新条目自身超上限 → overCap（拒绝，诚实提示）。 */
export function planQueueCapacity(
  items: AttachmentQueueItem[],
  incomingBytes: number,
  capBytes: number = ATTACHMENT_QUEUE_CAP_BYTES,
): CapacityPlan {
  if (incomingBytes > capBytes) {
    return { kept: items, evicted: [], overCap: true }
  }
  let used = items.reduce((sum, item) => sum + bytesOf(item), 0)
  if (used + incomingBytes <= capBytes) {
    return { kept: items, evicted: [], overCap: false }
  }
  const evicted: AttachmentQueueItem[] = []
  const evictableOrder = [...items].sort((a, b) => a.addedAt - b.addedAt)
  // 第一轮：释放已完成/失败/取消的（无在途风险）
  for (const item of [...evictableOrder].filter((i) => i.status !== 'queued' && i.status !== 'downloading')) {
    if (used + incomingBytes <= capBytes) break
    used -= bytesOf(item)
    evicted.push(item)
  }
  // 第二轮：仍不够 → 逐出最旧的未完成条目（诚实提示打断）
  if (used + incomingBytes > capBytes) {
    for (const item of evictableOrder) {
      if (evicted.includes(item)) continue
      if (used + incomingBytes <= capBytes) break
      used -= bytesOf(item)
      evicted.push(item)
    }
  }
  const evictedSet = new Set(evicted)
  return {
    kept: items.filter((item) => !evictedSet.has(item)),
    evicted,
    overCap: false,
  }
}

// ---- 下载执行（fetch → 流式读取 → Blob） ----

export interface DownloadProgress {
  loaded: number
  /** Content-Length 可得时为总字节；否则 null（进度不可信）。 */
  total: number | null
}

export interface DownloadResult {
  blob: Blob
  total: number | null
}

/** 下载一个附件为 Blob：ReadableStream reader 逐块累计并回调进度；
 * 无 body（jsdom/某些环境）→ 诚实退化为 blob()，进度只回调一次。
 * 调用方负责 AbortSignal（取消）与错误呈现。 */
export async function downloadAttachmentToBlob(
  url: string,
  options: {
    signal?: AbortSignal
    fetchImpl?: typeof fetch
    onProgress?: (progress: DownloadProgress) => void
  } = {},
): Promise<DownloadResult> {
  const doFetch = options.fetchImpl ?? fetch
  const response = await doFetch(url, { signal: options.signal })
  if (!response.ok) {
    throw new Error(`下载失败（HTTP ${response.status}）`)
  }
  const lengthHeader = response.headers.get('content-length')
  const total =
    lengthHeader !== null && Number.isFinite(Number(lengthHeader))
      ? Number(lengthHeader)
      : null
  const body = response.body
  if (body === null || typeof body.getReader !== 'function') {
    const blob = await response.blob()
    options.onProgress?.({ loaded: blob.size, total: total ?? blob.size })
    return { blob, total: total ?? blob.size }
  }
  const reader = body.getReader()
  const chunks: Uint8Array[] = []
  let loaded = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    if (value !== undefined) {
      chunks.push(value)
      loaded += value.byteLength
      options.onProgress?.({ loaded, total })
    }
  }
  const blob = new Blob(chunks as BlobPart[])
  return { blob, total: total ?? loaded }
}

/** 触发浏览器下载（object URL → anchor → 点击 → revoke）。 */
export function triggerBrowserDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = sanitizeAttachmentFilename(filename)
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}

/** 新 id（crypto.randomUUID 不可用时退化时间+随机）。 */
export function newAttachmentId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `att-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** 字节格式化（诚实口径：未知显示「大小未知」）。 */
export function formatAttachmentBytes(bytes: number | null): string {
  if (bytes === null || !Number.isFinite(bytes)) return '大小未知'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
