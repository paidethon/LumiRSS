/** open-item — 「一切皆可打开」的统一路由（P0-02 打开 payload 契约）。
 *
 * ResolvedItem.payload 按 kind 携带打开目标：
 * - rss            → payload.entryRef → Reader（选中条目；Reader 是
 *                    应用右栏/移动全屏，不改 section，返回语义与搜索一致）；
 * - bookmark       → itemType=rss 且带 rssItemRef → Reader；
 *                    其余 → 安全外链（仅绝对 http/https）；
 * - clip           → 剪藏 section（列表 + 阅读视图）；
 * - snapshot       → payload.pageUrl（服务端沙箱页，新标签）；
 * - obsidian_note  → Obsidian section；
 * - 其余/失效      → 不可打开（isOpenable=false，调用方给禁用态）。
 *
 * 纯 UI 路由（Zustand UI store + window.open），零网络；引用只带 ref
 * 没有卡片数据时用 resolveAndOpen 先经 POST /api/v1/resolve 补齐。 */

import type { ResolvedItem } from '../api/types'
import { resolveItems } from '../api/client'
import { safeExternalHttpUrl } from './safe-external-http-url'
import { useReaderUi } from '../store/reader-ui'

/** payload 容错读字符串字段。 */
function payloadString(item: ResolvedItem, key: string): string | null {
  const value = item.payload[key]
  return typeof value === 'string' && value !== '' ? value : null
}

/** 安全外链（绝对 http/https 才放行；新标签 + noopener）。 */
export function openExternalUrl(url: string | null | undefined): boolean {
  const safe = safeExternalHttpUrl(url ?? null)
  if (safe === null) return false
  window.open(safe, '_blank', 'noopener,noreferrer')
  return true
}

/** 该卡片是否可打开（失效/未知 kind 且无安全外链 → 不可）。 */
export function isOpenable(item: ResolvedItem): boolean {
  if (item.stale) return false
  switch (item.kind) {
    case 'rss':
      return payloadString(item, 'entryRef') !== null || item.ref.startsWith('rss:')
    case 'bookmark':
      return (
        (payloadString(item, 'itemType') === 'rss' &&
          payloadString(item, 'rssItemRef') !== null) ||
        item.url != null
      )
    case 'clip':
    case 'obsidian_note':
      return true
    case 'snapshot':
      return payloadString(item, 'pageUrl') !== null
    default:
      // 未知 kind：仅当有安全外链时才宣称可打开。
      return safeExternalHttpUrl(item.url ?? null) !== null
  }
}

/** 按 kind 路由打开一张已解析卡片；返回是否真的发起了打开。 */
export function openResolvedItem(item: ResolvedItem): boolean {
  if (item.stale) return false
  const ui = useReaderUi.getState()
  switch (item.kind) {
    case 'rss': {
      const entryRef =
        payloadString(item, 'entryRef') ??
        (item.ref.startsWith('rss:') ? item.ref.slice('rss:'.length) : null)
      if (entryRef === null) return false
      ui.selectEntry(entryRef)
      return true
    }
    case 'bookmark': {
      const rssItemRef = payloadString(item, 'rssItemRef')
      if (payloadString(item, 'itemType') === 'rss' && rssItemRef !== null) {
        const entryRef = rssItemRef.startsWith('rss:') ? rssItemRef.slice('rss:'.length) : rssItemRef
        if (entryRef !== '') {
          ui.selectEntry(entryRef)
          return true
        }
      }
      return openExternalUrl(item.url)
    }
    case 'clip':
      ui.selectSection('clips')
      return true
    case 'snapshot': {
      const pageUrl = payloadString(item, 'pageUrl')
      // 服务端沙箱快照页是同源绝对路径；补 origin 成绝对 URL 新开标签。
      if (pageUrl !== null && pageUrl.startsWith('/')) {
        window.open(`${window.location.origin}${pageUrl}`, '_blank', 'noopener,noreferrer')
        return true
      }
      return false
    }
    case 'obsidian_note':
      ui.selectSection('obsidian')
      return true
    default:
      return openExternalUrl(item.url)
  }
}

/** 只有 ref（无卡片）时的打开路径：先 resolve 拿 title+payload，
 * 再按同一 kind 路由。返回解析结果（null = 解析请求本身失败）；
 * stale 目标不发起打开，由调用方按返回值给失效反馈。 */
export async function resolveAndOpen(ref: string): Promise<ResolvedItem | null> {
  const { items } = await resolveItems([ref])
  const item = items[0] ?? null
  if (item !== null && !item.stale) {
    openResolvedItem(item)
  }
  return item
}
