/** reader-fonts 测试 — 0012 Gate 2/3。
 *
 * jsdom 无 FontFace / document.fonts / indexedDB，测试内建零依赖 stub：
 * - FakeFontFace：记录 family/source，可注入 load 失败；
 * - FakeIdb：最小 IndexedDB（单 object store，promise 化）。
 * 覆盖：WOFF2 校验、重复导入去重、URL 白名单、删除正在使用的字体、
 * IndexedDB unavailable、load rejection、恢复注册。 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  deleteFont,
  fontFamilyName,
  FontError,
  importLocalFont,
  importUrlFont,
  isWoff2Bytes,
  listLocalFonts,
  restoreLocalFonts,
} from '../lib/reader-fonts'

// ---- stub：FontFace ----

const loadedFaces: FakeFontFace[] = []

class FakeFontFace {
  readonly family: string
  readonly source: ArrayBuffer | string
  /** 注入 load 失败 */
  failLoad = false
  constructor(family: string, source: ArrayBuffer | string) {
    this.family = family
    this.source = source
  }
  async load(): Promise<FakeFontFace> {
    if (this.failLoad) throw new TypeError('load failed')
    return this
  }
}

// ---- stub：document.fonts ----

class FakeFontFaceSet {
  private set = new Set<FakeFontFace>()
  add(face: FakeFontFace): FakeFontFaceSet {
    this.set.add(face)
    loadedFaces.push(face)
    return this
  }
  delete(face: FakeFontFace): boolean {
    return this.set.delete(face)
  }
  [Symbol.iterator]() {
    return this.set.values()
  }
  /** 测试断言用 */
  families(): string[] {
    return [...this.set].map((f) => f.family)
  }
}

// ---- stub：IndexedDB ----

class FakeRequest<T> {
  onsuccess: (() => void) | null = null
  onerror: (() => void) | null = null
  onupgradeneeded: (() => void) | null = null
  result!: T
  error: DOMException | null = null
}

class FakeStore {
  readonly map = new Map<string, Record<string, unknown>>()
  get(id: string): FakeRequest<Record<string, unknown> | undefined> {
    const r = new FakeRequest<Record<string, unknown> | undefined>()
    r.result = this.map.get(id)
    queueMicrotask(() => r.onsuccess?.())
    return r
  }
  put(record: Record<string, unknown>): FakeRequest<IDBValidKey> {
    const r = new FakeRequest<IDBValidKey>()
    this.map.set(record.id as string, record)
    queueMicrotask(() => r.onsuccess?.())
    return r
  }
  delete(id: string): FakeRequest<undefined> {
    const r = new FakeRequest<undefined>()
    this.map.delete(id)
    queueMicrotask(() => r.onsuccess?.())
    return r
  }
  getAll(): FakeRequest<Record<string, unknown>[]> {
    const r = new FakeRequest<Record<string, unknown>[]>()
    r.result = [...this.map.values()]
    queueMicrotask(() => r.onsuccess?.())
    return r
  }
}

class FakeDb {
  readonly store = new FakeStore()
  closed = false
  objectStoreNames = { contains: () => true }
  transaction(): {
    objectStore: () => FakeStore
  } {
    return { objectStore: () => this.store }
  }
  close(): void {
    this.closed = true
  }
}

let db: FakeDb
let idbAvailable = true

function installStubs(failLoadFor: string[] = []): void {
  const fonts = new FakeFontFaceSet()
  vi.stubGlobal('FontFace', class extends FakeFontFace {
    constructor(family: string, source: ArrayBuffer | string) {
      super(family, source)
      if (failLoadFor.includes(family)) this.failLoad = true
    }
  })
  Object.defineProperty(document, 'fonts', { value: fonts, configurable: true, writable: true })
  const fakeOpen = ():
    | (FakeRequest<FakeDb> & IDBOpenDBRequest)
    | FakeRequest<FakeDb> => {
    const r = new FakeRequest<FakeDb>()
    if (!idbAvailable) {
      r.error = new DOMException('blocked')
      queueMicrotask(() => r.onerror?.())
      return r as FakeRequest<FakeDb>
    }
    r.result = db
    queueMicrotask(() => r.onsuccess?.())
    return r as FakeRequest<FakeDb> & IDBOpenDBRequest
  }
  vi.stubGlobal('indexedDB', { open: fakeOpen })
}

// ---- 测试工具 ----

/** 构造带 WOFF2 魔数头的伪字体文件（内容差异 → 不同 hash id）。 */
function woff2File(name: string, fill: number, type = 'font/woff2'): File {
  const bytes = new Uint8Array(64)
  bytes.set([0x77, 0x4f, 0x46, 0x32]) // 'wOF2'
  bytes.fill(fill, 4)
  return new File([bytes], name, { type })
}

beforeEach(() => {
  db = new FakeDb()
  idbAvailable = true
  loadedFaces.length = 0
  vi.unstubAllGlobals()
})

describe('isWoff2Bytes — 魔数校验', () => {
  it('接受 wOF2 头', () => {
    expect(isWoff2Bytes(new Uint8Array([0x77, 0x4f, 0x46, 0x32, 0, 0]))).toBe(true)
  })
  it('拒绝 TTF（OTTO/\\x00\\x01）与过短输入', () => {
    expect(isWoff2Bytes(new Uint8Array([0x00, 0x01, 0x00, 0x00]))).toBe(false)
    expect(isWoff2Bytes(new Uint8Array([0x4f, 0x54, 0x54, 0x4f]))).toBe(false)
    expect(isWoff2Bytes(new Uint8Array([0x77, 0x4f]))).toBe(false)
  })
})

describe('importLocalFont — 本地 WOFF2 导入', () => {
  it('合法文件 → 存储 + 注册 FontFace', async () => {
    installStubs()
    const { font, duplicate } = await importLocalFont(woff2File('MyFont.woff2', 1), '我的字体')
    expect(duplicate).toBe(false)
    expect(font.id).toMatch(/^font-[0-9a-f]{16}$/)
    expect(font.name).toBe('我的字体')
    expect(font.source).toBe('local')
    expect(font.fileName).toBe('MyFont.woff2')
    expect(font.size).toBe(64)
    expect(db.store.map.size).toBe(1)
    expect(loadedFaces.some((f) => f.family === fontFamilyName(font.id))).toBe(true)
  })

  it('扩展名不符 → not-woff2', async () => {
    installStubs()
    const file = new File([new Uint8Array([0x77, 0x4f, 0x46, 0x32, 0])], 'font.ttf', {
      type: 'font/ttf',
    })
    await expect(importLocalFont(file)).rejects.toMatchObject({ code: 'not-woff2' })
  })

  it('扩展名对但内容是伪造（魔数错）→ not-woff2', async () => {
    installStubs()
    const file = new File([new Uint8Array([0, 1, 2, 3, 4])], 'fake.woff2', { type: 'font/woff2' })
    await expect(importLocalFont(file)).rejects.toMatchObject({ code: 'not-woff2' })
  })

  it('损坏字体（FontFace load 失败）→ load-failed，不入库', async () => {
    installStubs()
    // 所有 family 都 load 失败
    vi.stubGlobal(
      'FontFace',
      class extends FakeFontFace {
        failLoad = true
      },
    )
    await expect(importLocalFont(woff2File('broken.woff2', 2))).rejects.toMatchObject({
      code: 'load-failed',
    })
    expect(db.store.map.size).toBe(0)
  })

  it('重复导入同一内容 → duplicate，复用已有 id', async () => {
    installStubs()
    const first = await importLocalFont(woff2File('a.woff2', 7), '第一次')
    const second = await importLocalFont(woff2File('重命名也行.woff2', 7), '第二次')
    expect(second.duplicate).toBe(true)
    expect(second.font.id).toBe(first.font.id)
    expect(db.store.map.size).toBe(1)
  })

  it('IndexedDB 不可用 → idb-unavailable，不崩溃', async () => {
    installStubs()
    idbAvailable = false
    await expect(importLocalFont(woff2File('a.woff2', 3))).rejects.toMatchObject({
      code: 'idb-unavailable',
    })
  })
})

describe('importUrlFont — 字体 URL（Gate 3）', () => {
  it('合法 https URL → 注册成功，不落 IndexedDB', async () => {
    installStubs()
    const font = await importUrlFont('https://cdn.example.com/fonts/CJK.woff2', '思源宋体')
    expect(font.source).toBe('url')
    expect(font.url).toBe('https://cdn.example.com/fonts/CJK.woff2')
    expect(font.name).toBe('思源宋体')
    expect(db.store.map.size).toBe(0) // URL 字体不入 IndexedDB
    expect(loadedFaces.some((f) => f.family === fontFamilyName(font.id))).toBe(true)
  })

  it('非法协议 / 相对路径 → invalid-url', async () => {
    installStubs()
    await expect(importUrlFont('javascript:alert(1)', 'x')).rejects.toMatchObject({
      code: 'invalid-url',
    })
    await expect(importUrlFont('/fonts/a.woff2', 'x')).rejects.toMatchObject({
      code: 'invalid-url',
    })
  })

  it('远程加载失败（含 CORS）→ network', async () => {
    installStubs()
    vi.stubGlobal(
      'FontFace',
      class extends FakeFontFace {
        failLoad = true
      },
    )
    await expect(
      importUrlFont('https://no-cors.example.com/a.woff2', 'x'),
    ).rejects.toMatchObject({ code: 'network' })
  })
})

describe('删除与恢复', () => {
  it('删除字体 → IndexedDB 记录与 FontFace 均移除', async () => {
    installStubs()
    const { font } = await importLocalFont(woff2File('del.woff2', 9), '待删')
    const family = fontFamilyName(font.id)
    const fonts = document.fonts as unknown as FakeFontFaceSet
    expect(fonts.families()).toContain(family)
    await deleteFont(font.id)
    expect(db.store.map.has(font.id)).toBe(false)
    expect(fonts.families()).not.toContain(family)
  })

  it('删除不存在的 id → 静默成功', async () => {
    installStubs()
    await expect(deleteFont('font-0000000000000000')).resolves.toBeUndefined()
  })

  it('restoreLocalFonts → 刷新后重新注册全部本地字体', async () => {
    installStubs()
    const a = await importLocalFont(woff2File('a.woff2', 1), 'A')
    const b = await importLocalFont(woff2File('b.woff2', 2), 'B')
    // 模拟刷新：清掉已注册 faces，只留 IndexedDB
    const fonts = document.fonts as unknown as FakeFontFaceSet
    const families = fonts.families()
    for (const f of [...fonts]) fonts.delete(f)
    expect(fonts.families()).toEqual([])
    const restored = await restoreLocalFonts()
    expect(restored.map((f) => f.id).sort()).toEqual([a.font.id, b.font.id].sort())
    for (const fam of families) {
      expect(loadedFaces.some((f) => f.family === fam)).toBe(true)
    }
  })

  it('listLocalFonts → IndexedDB 不可用时返回空列表', async () => {
    installStubs()
    idbAvailable = false
    await expect(listLocalFonts()).resolves.toEqual([])
    await expect(restoreLocalFonts()).resolves.toEqual([])
  })

  it('restoreLocalFonts：单个损坏字体被跳过，其余正常恢复', async () => {
    installStubs()
    await importLocalFont(woff2File('ok.woff2', 4), 'OK')
    // 直接往 store 塞一条无 blob 的损坏记录
    db.store.map.set('font-deadbeefdeadbeef', {
      id: 'font-deadbeefdeadbeef',
      name: '损坏',
      source: 'local',
      url: '',
      fileName: 'x.woff2',
      size: 1,
      createdAt: 1,
      // 无 blob 字段
    })
    const restored = await restoreLocalFonts()
    expect(restored).toHaveLength(2) // 元信息仍列出（选择器可显示「缺失」）
  })
})

describe('fontFamilyName — 稳定命名', () => {
  it('同 id 永远同名，带隔离前缀', () => {
    expect(fontFamilyName('font-abc123')).toBe('LumiCustom-font-abc123')
    expect(fontFamilyName('font-abc123')).toBe(fontFamilyName('font-abc123'))
  })
})

describe('FontError — 错误结构', () => {
  it('携带 code + message', () => {
    const e = new FontError('quota-exceeded', 'x')
    expect(e.code).toBe('quota-exceeded')
    expect(e).toBeInstanceOf(Error)
  })
})
