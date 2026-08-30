/** reader-fonts — Reader 自定义字体管理（0012 Gate 2 + Gate 3）。
 *
 * 两条通道，统一注册协议：
 * - local：用户上传 WOFF2 → 校验 → IndexedDB 存 Blob → FontFace 加载；
 * - url：http/https 直链（大体积中文字体自托管场景）→ FontFace 直接
 *   挂远程 URL，不下载复制进 IndexedDB（隐私：浏览器会向该服务器
 *   发请求，设置 UI 需提示）。
 *
 * 安全/健壮性不变式：
 * - 仅 WOFF2（扩展名 + MIME + FontFace 实际可加载性三重校验）；
 * - 稳定 font id = 'font-' + 内容 hash（重复导入去重）；
 * - IndexedDB unavailable / quota / load rejection → 结构化错误返回，
 *   绝不抛未捕获异常导致应用崩溃；
 * - 删除正在使用的字体 → 由调用方（store）解除引用，Reader 回退
 *   字体栈；本模块只负责注册表一致性。
 *
 * Web 标准 API（FontFace / document.fonts / IndexedDB），零第三方依赖。 */

import type { ReaderCustomFont } from '../store/app-settings'

const DB_NAME = 'lumirss-fonts'
const DB_VERSION = 1
const STORE = 'fonts'

/** 注册名前缀：仅用于 FontFace family，避免与系统字体名冲突。 */
const FAMILY_PREFIX = 'LumiCustom-'

export type FontErrorCode =
  | 'not-woff2' // 扩展名/MIME 不符
  | 'load-failed' // FontFace 无法加载（损坏/伪造 woff2）
  | 'idb-unavailable' // IndexedDB 不可用（隐私模式等）
  | 'quota-exceeded' // 存储配额
  | 'invalid-url' // URL 白名单不过
  | 'network' // 远程字体加载失败（含 CORS）
  | 'duplicate' // 内容重复（非错误，附已有 id）
  | 'unknown'

export class FontError extends Error {
  readonly code: FontErrorCode
  readonly existingId?: string
  constructor(code: FontErrorCode, message: string, existingId?: string) {
    super(message)
    this.name = 'FontError'
    this.code = code
    this.existingId = existingId
  }
}

interface FontRecord extends ReaderCustomFont {
  /** local 模式：字体二进制 */
  blob?: Blob
}

// ---- IndexedDB（薄封装，全部失败转 FontError） ----

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new FontError('idb-unavailable', 'IndexedDB 不可用'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () =>
      reject(new FontError('idb-unavailable', req.error?.message ?? 'IndexedDB 打开失败'))
  })
}

function tx<T>(db: IDBDatabase, mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode)
    const req = fn(t.objectStore(STORE))
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => {
      const name = req.error?.name ?? ''
      if (name === 'QuotaExceededError') {
        reject(new FontError('quota-exceeded', '存储空间不足'))
      } else {
        reject(new FontError('unknown', req.error?.message ?? 'IndexedDB 操作失败'))
      }
    }
  })
}

// ---- 稳定 id：内容 hash（FNV-1a 64 → hex，够用且零依赖） ----

function hashBytes(bytes: Uint8Array): string {
  // FNV-1a 32 位 ×2（不同初始值）拼 64 bit —— 碰撞率对本场景足够
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (let i = 0; i < bytes.length; i++) {
    h1 ^= bytes[i]
    h1 = Math.imul(h1, 0x01000193) >>> 0
    h2 ^= (bytes[i] + i) & 0xff
    h2 = Math.imul(h2, 0x85ebca6b) >>> 0
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')
}

/** FontFace family 注册名（稳定：同 id 永远同名）。 */
export function fontFamilyName(id: string): string {
  return `${FAMILY_PREFIX}${id}`
}

/** URL 字体的稳定 id（与 importUrlFont 内部一致，供 store 无副作用推导注册名）。 */
export function fontIdFromUrl(url: string): string {
  return `font-${hashBytes(new TextEncoder().encode(url))}`
}

// ---- 校验 ----

const WOFF2_MAGIC = [0x77, 0x4f, 0x46, 0x32] // 'wOF2'

/** 校验 WOFF2 文件头魔数（比扩展名/MIME 更强，防伪造）。 */
export function isWoff2Bytes(bytes: Uint8Array): boolean {
  if (bytes.length < 4) return false
  return WOFF2_MAGIC.every((b, i) => bytes[i] === b)
}

/** 实际加载校验：FontFace 构造 + load()，拒绝损坏/伪造字体。 */
async function verifyLoadable(family: string, source: ArrayBuffer | string): Promise<void> {
  const face = new FontFace(family, source)
  try {
    await face.load()
  } catch {
    throw new FontError('load-failed', '字体文件无法被浏览器加载（可能已损坏）')
  }
}

// ---- 导入：本地 WOFF2 ----

export interface ImportResult {
  font: ReaderCustomFont
  /** 重复导入时为 true（font 为已有条目） */
  duplicate: boolean
}

/** 导入本地 WOFF2 文件：三重校验（扩展名+魔数+FontFace load）→
 * IndexedDB 持久化。重复内容返回已有条目。 */
export async function importLocalFont(file: File, displayName?: string): Promise<ImportResult> {
  // 1. 扩展名 / MIME（快速失败）
  const isWoff2Name = file.name.toLowerCase().endsWith('.woff2')
  const isWoff2Mime = file.type === 'font/woff2' || file.type === ''
  if (!isWoff2Name || !isWoff2Mime) {
    throw new FontError('not-woff2', '仅支持 WOFF2 字体文件（.woff2）')
  }

  // 2. 读内容 + 魔数
  const buffer = await file.arrayBuffer()
  if (!isWoff2Bytes(new Uint8Array(buffer.slice(0, 4)))) {
    throw new FontError('not-woff2', '文件内容不是有效的 WOFF2 字体')
  }

  // 3. 稳定 id（内容 hash → 重复导入去重）
  const id = `font-${hashBytes(new Uint8Array(buffer))}`
  const family = fontFamilyName(id)

  // 4. 实际可加载性
  await verifyLoadable(family, buffer)

  const db = await openDb()
  try {
    const existing = await tx<FontRecord | undefined>(db, 'readonly', (s) => s.get(id))
    if (existing !== undefined) {
      // 已有：确保仍注册着（刷新场景），返回已有条目
      await registerFontFace(family, existing.blob ?? buffer)
      return { font: toMeta(existing), duplicate: true }
    }
    const record: FontRecord = {
      id,
      name: (displayName?.trim() || file.name.replace(/\.woff2$/i, '')).slice(0, 64),
      source: 'local',
      url: '',
      fileName: file.name.slice(0, 128),
      size: file.size,
      createdAt: Date.now(),
      blob: file,
    }
    await tx(db, 'readwrite', (s) => s.put(record))
    await registerFontFace(family, record.blob ?? file)
    return { font: toMeta(record), duplicate: false }
  } finally {
    db.close()
  }
}

// ---- 导入：字体 URL（Gate 3） ----

/** 校验并加载远程字体 URL。成功返回字体元信息（不落 IndexedDB）。
 * 失败区分 invalid-url / network（含 CORS）。 */
export async function importUrlFont(url: string, displayName: string): Promise<ReaderCustomFont> {
  if (typeof url !== 'string') throw new FontError('invalid-url', '无效的字体 URL')
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    throw new FontError('invalid-url', '无效的字体 URL')
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new FontError('invalid-url', '字体 URL 仅支持 http/https')
  }

  const id = fontIdFromUrl(url)
  const family = fontFamilyName(id)
  // FontFace 挂远程 URL —— 由浏览器直接请求（CORS 失败 → network 错误）
  const face = new FontFace(family, `url(${JSON.stringify(url)})`)
  try {
    await face.load()
  } catch {
    throw new FontError(
      'network',
      '远程字体加载失败（地址错误、服务器不可达或未允许跨域访问）',
    )
  }
  document.fonts.add(face)
  return {
    id,
    name: (displayName.trim() || parsed.pathname.split('/').pop() || url).slice(0, 64),
    source: 'url',
    url,
    fileName: '',
    size: 0,
    createdAt: Date.now(),
  }
}

// ---- 注册 / 恢复 ----

/** 把 Blob/ArrayBuffer/URL 注册为可用 FontFace（幂等：同名已存在则跳过）。 */
export async function registerFontFace(family: string, source: Blob | ArrayBuffer): Promise<void> {
  const existing = [...document.fonts].find((f) => f.family === family)
  if (existing !== undefined) {
    try {
      await existing.load()
    } catch {
      document.fonts.delete(existing)
    }
    return
  }
  const face = new FontFace(
    family,
    source instanceof Blob ? await source.arrayBuffer() : source,
  )
  try {
    await face.load()
    document.fonts.add(face)
  } catch {
    // 注册失败不抛：调用方按「字体缺失 → fallback」处理
  }
}

/** 应用启动时恢复：列出 IndexedDB 所有 local 字体并重新注册。
 * IndexedDB 不可用 / 单个字体损坏 → 静默跳过（不阻塞启动）。 */
export async function restoreLocalFonts(): Promise<ReaderCustomFont[]> {
  try {
    const db = await openDb()
    try {
      const records = await tx<FontRecord[]>(db, 'readonly', (s) => s.getAll())
      const fonts: ReaderCustomFont[] = []
      for (const r of records) {
        if (r.blob !== undefined) {
          await registerFontFace(fontFamilyName(r.id), r.blob)
        }
        fonts.push(toMeta(r))
      }
      return fonts
    } finally {
      db.close()
    }
  } catch {
    return []
  }
}

// ---- 查询 / 删除 ----

/** 列出已存储的 local 字体（不含 Blob）。IndexedDB 不可用 → 空列表。 */
export async function listLocalFonts(): Promise<ReaderCustomFont[]> {
  try {
    const db = await openDb()
    try {
      const records = await tx<FontRecord[]>(db, 'readonly', (s) => s.getAll())
      return records.map(toMeta)
    } finally {
      db.close()
    }
  } catch {
    return []
  }
}

export async function getLocalFont(id: string): Promise<ReaderCustomFont | null> {
  try {
    const db = await openDb()
    try {
      const r = await tx<FontRecord | undefined>(db, 'readonly', (s) => s.get(id))
      return r === undefined ? null : toMeta(r)
    } finally {
      db.close()
    }
  } catch {
    return null
  }
}

/** 删除字体（IndexedDB 记录 + FontFace 注销）。不存在时静默成功。 */
export async function deleteFont(id: string): Promise<void> {
  try {
    const db = await openDb()
    try {
      await tx(db, 'readwrite', (s) => s.delete(id))
    } finally {
      db.close()
    }
  } catch {
    // IndexedDB 不可用：仍尝试注销 FontFace
  }
  const family = fontFamilyName(id)
  for (const face of [...document.fonts]) {
    if (face.family === family) document.fonts.delete(face)
  }
}

function toMeta(r: FontRecord): ReaderCustomFont {
  const { blob: _blob, ...meta } = r
  return meta
}
