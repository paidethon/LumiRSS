/** read-later store — 稍后读 marker（0011 修正补充 §12/§36）。
 *
 * 语义（与收藏独立）：稍后读 = 现在不看之后回来读；收藏 = 值得长期
 * 保存。readLater 与 read/starred 互不覆盖（§28）。
 *
 * 数据层：FreshRSS 无 read-later marker（真源原则 §36：FreshRSS 只管
 * RSS 领域状态），Lumi 只存最小 marker 集合（entryRef set + 加入时间
 * 排序保序），localStorage 单 key 持久化（与 app-settings 同模式；
 * 未来 0017 统一设置时可迁服务端）。不复制文章字段（title/feed 等
 * 仍从 Query cache 取）。
 *
 * readLaterWorkspace 视图（客户端过滤）：EntryList 在 view=read-later
 * 时对已加载条目过滤 isReadLater，翻页后新命中条目自动出现。 */

import { create } from 'zustand'

const STORAGE_KEY = 'lumirss-read-later'
/** 加入时间有序 entryRef 列表（新加入的在头部，同 store 数据排序）。 */
interface ReadLaterState {
  /** 有序列表：[entryRef, addedAtMs][]，新加入 unshift 头部 */
  items: { entryRef: string; addedAt: number }[]
  isReadLater: (entryRef: string) => boolean
  /** set 语义：value=true 加入 / false 移除（§12 非 toggle 语义由调用方决定目标值） */
  setReadLater: (entryRef: string, value: boolean) => void
  toggleReadLater: (entryRef: string) => boolean
}

function load(): { entryRef: string; addedAt: number }[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (it): it is { entryRef: string; addedAt: number } =>
        typeof it === 'object' &&
        it !== null &&
        typeof (it as { entryRef?: unknown }).entryRef === 'string' &&
        typeof (it as { addedAt?: unknown }).addedAt === 'number',
    )
  } catch {
    return []
  }
}

function persist(items: { entryRef: string; addedAt: number }[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    // localStorage 不可用：退化为会话内状态，不报错
  }
}

export const useReadLater = create<ReadLaterState>((set, get) => ({
  items: load(),
  isReadLater: (entryRef) => get().items.some((it) => it.entryRef === entryRef),
  setReadLater: (entryRef, value) =>
    set((state) => {
      const exists = state.items.some((it) => it.entryRef === entryRef)
      if (value && !exists) {
        const next = [{ entryRef, addedAt: Date.now() }, ...state.items]
        persist(next)
        return { items: next }
      }
      if (!value && exists) {
        const next = state.items.filter((it) => it.entryRef !== entryRef)
        persist(next)
        return { items: next }
      }
      return state // 幂等：目标状态已满足
    }),
  toggleReadLater: (entryRef) => {
    const next = !get().isReadLater(entryRef)
    get().setReadLater(entryRef, next)
    return next
  },
}))
