/** search-basket — N147 搜索结果暂存篮（设备本地，localStorage）。
 *
 * 设备本地的「引用篮」：搜索结果行勾选加入，跨页面/跨会话保留；
 * 按 entryRef 去重，上限 100 条（超出丢弃 newest 之外的部分并诚实
 * 计数）。篮里只存引用元数据（ref/标题/来源/时间/URL），绝不存正文。
 *
 * 登出清理：经 lib/auth-reset 的统一出口调用 clearBasketOnLogout
 * （换账号绝不看到上一账号的暂存引用）。localStorage 不可用（隐私
 * 模式等）时降级为会话内可用，不报错。
 */

import { create } from 'zustand'

const STORAGE_KEY = 'lumirss-search-basket'
export const SEARCH_BASKET_LIMIT = 100

/** 篮内一项：RSS 条目引用 + 列表元数据（与 SearchItem 同名字段）。 */
export interface SearchBasketItem {
  entryRef: string
  title: string
  feedTitle: string
  publishedAt: string
  url: string | null
  addedAt: string
}

export interface AddManyReport {
  basket: SearchBasketItem[]
  added: number
  duplicated: number
  droppedOverCap: number
}

function normalizeItem(raw: unknown): SearchBasketItem | null {
  if (typeof raw !== 'object' || raw === null) return null
  const record = raw as Record<string, unknown>
  if (typeof record.entryRef !== 'string' || record.entryRef === '') return null
  return {
    entryRef: record.entryRef,
    title: typeof record.title === 'string' ? record.title : '',
    feedTitle: typeof record.feedTitle === 'string' ? record.feedTitle : '',
    publishedAt: typeof record.publishedAt === 'string' ? record.publishedAt : '',
    url: typeof record.url === 'string' ? record.url : null,
    addedAt: typeof record.addedAt === 'string' ? record.addedAt : '',
  }
}

/** 读取并归一化 localStorage 篮（坏 JSON / 异形项容忍；去重 + 截断）。 */
export function readBasketItems(): SearchBasketItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const seen = new Set<string>()
    const items: SearchBasketItem[] = []
    for (const rawItem of parsed.slice(0, SEARCH_BASKET_LIMIT)) {
      const item = normalizeItem(rawItem)
      if (item === null || seen.has(item.entryRef)) continue
      seen.add(item.entryRef)
      items.push(item)
    }
    return items
  } catch {
    return []
  }
}

function persist(items: SearchBasketItem[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, SEARCH_BASKET_LIMIT)))
  } catch {
    // localStorage 不可用：篮降级为会话内状态，不报错
  }
}

/** 纯函数：把若干条目并入篮（按 entryRef 去重、上限截断）并诚实上报。 */
export function addBasketItems(
  current: SearchBasketItem[],
  incoming: Omit<SearchBasketItem, 'addedAt'>[],
): AddManyReport {
  const seen = new Set(current.map((item) => item.entryRef))
  let added = 0
  let duplicated = 0
  const next = [...current]
  for (const raw of incoming) {
    const entryRef = typeof raw.entryRef === 'string' ? raw.entryRef : ''
    if (!entryRef) continue
    if (seen.has(entryRef)) {
      duplicated += 1
      continue
    }
    if (next.length >= SEARCH_BASKET_LIMIT) {
      // 上限保护：超过部分不计入（counted as dropped by caller sum）。
      continue
    }
    seen.add(entryRef)
    next.push({ ...raw, entryRef, addedAt: new Date().toISOString() })
    added += 1
  }
  const droppedOverCap = incoming.length - added - duplicated
  const basket = next.slice(0, SEARCH_BASKET_LIMIT)
  return { basket, added, duplicated, droppedOverCap: Math.max(0, droppedOverCap) }
}

/** 纯函数：移除一项（set 语义：不存在也安全）。 */
export function removeBasketItem(
  items: SearchBasketItem[],
  entryRef: string,
): SearchBasketItem[] {
  return items.filter((item) => item.entryRef !== entryRef)
}

/** 登出清理（幂等）：清 localStorage + 重置 store。 */
export function clearBasketOnLogout(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 忽略 */
  }
  useSearchBasket.getState().reset()
}

interface SearchBasketState {
  items: SearchBasketItem[]
  lastReport: AddManyReport | null
  /** 从 localStorage 重新装载（组件挂载时调用一次即可）。 */
  load: () => void
  addMany: (incoming: Omit<SearchBasketItem, 'addedAt'>[]) => AddManyReport
  remove: (entryRef: string) => void
  clear: () => void
  reset: () => void
}

/** 暂存篮 store（localStorage 持久化；SearchPage 行勾选与面板共享）。 */
export const useSearchBasket = create<SearchBasketState>((set, get) => ({
  items: [],
  lastReport: null,
  load: () => set({ items: readBasketItems() }),
  addMany: (incoming) => {
    const report = addBasketItems(get().items, incoming)
    persist(report.basket)
    set({ items: report.basket, lastReport: report })
    return report
  },
  remove: (entryRef) => {
    const next = removeBasketItem(get().items, entryRef)
    persist(next)
    set({ items: next })
  },
  clear: () => {
    persist([])
    set({ items: [], lastReport: null })
  },
  reset: () => set({ items: [], lastReport: null }),
}))

/** 篮条目 → markdown 引用清单（与 F073 导出口径一致：标题/来源/日期/
 * 链接；纯文本，无正文）。 */
export function basketToMarkdown(items: SearchBasketItem[]): string {
  const lines = ['# 搜索暂存篮', '']
  for (const item of items) {
    const date = (item.publishedAt || '').slice(0, 10)
    const parts = [`- ${item.title || item.entryRef}`]
    const meta: string[] = []
    if (item.feedTitle) meta.push(item.feedTitle)
    if (date) meta.push(date)
    if (meta.length > 0) parts.push(`（${meta.join(' · ')}）`)
    lines.push(parts.join(' '))
    if (item.url) lines.push(`  ${item.url}`)
  }
  if (items.length === 0) lines.push('（空）')
  lines.push('')
  return lines.join('\n')
}
