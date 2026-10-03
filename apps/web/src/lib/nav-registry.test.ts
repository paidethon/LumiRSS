/** nav-registry — 唯一真源结构守卫（R3 契约 §3）。
 *
 * 钉住：id 唯一、八类 sourceType 齐全、组序 阅读→内容来源→工具、
 * 底栏四 tab 成员与顺序、既有入口全保留、深链 id 约定、
 * sourceTypeSourceOrder 与 SourcesPage 现行 TYPE_ORDER 的前六位一致。 */

import { describe, expect, it } from 'vitest'
import {
  NAV_ENTRIES,
  navEntriesForSurface,
  navGroupsForSidebar,
  navTargetOf,
  settingsCategoryOf,
  sourceTypeSourceOrder,
} from './nav-registry'

describe('nav-registry（唯一真源）', () => {
  it('id 唯一且 order 升序排列', () => {
    const ids = NAV_ENTRIES.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    const orders = NAV_ENTRIES.map((e) => e.order)
    expect([...orders].sort((a, b) => a - b)).toEqual(orders)
  })

  it('八类 sourceType 齐全（契约 §3）', () => {
    const types = new Set(
      NAV_ENTRIES.map((e) => e.sourceType).filter((t) => t !== undefined),
    )
    for (const t of [
      'rss',
      'bookmark',
      'clip',
      'snapshot',
      'inbox',
      'api_source',
      'newsletter',
      'obsidian',
    ] as const) {
      expect(types.has(t)).toBe(true)
    }
  })

  it('组序：阅读 → 内容来源 → 工具，组内 order 升序', () => {
    const groups = navGroupsForSidebar()
    expect(groups.map((g) => g.group)).toEqual(['reading', 'sources', 'tools'])
    for (const g of groups) {
      const orders = g.entries.map((e) => e.order)
      expect([...orders].sort((a, b) => a - b)).toEqual(orders)
    }
  })

  it('既有侧栏入口全保留', () => {
    const labels = navEntriesForSurface('sidebar').map((e) => e.label)
    for (const label of [
      '全部信息源',
      'RSS 订阅',
      '来源',
      '书签',
      '网页剪藏',
      '网页快照',
      '收件箱',
      'API 来源',
      '邮件简报',
      'Obsidian 库',
      '稍后读',
      '收藏',
      '搜索',
      '工作区',
      'Agent 工作台',
      'RAG 索引',
      '标签 / 图谱',
    ]) {
      expect(labels).toContain(label)
    }
  })

  it('底栏四 tab：首页/来源/搜索/收藏（order 决定排列）', () => {
    const tabs = navEntriesForSurface('tabbar')
    expect(tabs.map((t) => t.shortLabel)).toEqual(['首页', '来源', '搜索', '收藏'])
    expect(tabs.map((t) => navTargetOf(t).section)).toEqual([
      'home',
      'sources',
      'search',
      'favorites',
    ])
  })

  it('navTargetOf：home 视图入口与 RSS scope 入口', () => {
    const readLater = NAV_ENTRIES.find((e) => e.id === 'home:read-later')
    expect(readLater).toBeDefined()
    if (readLater) {
      expect(navTargetOf(readLater)).toEqual({
        section: 'home',
        scope: { kind: 'all' },
        view: 'read-later',
      })
    }
    const rss = NAV_ENTRIES.find((e) => e.id === 'source:rss')
    expect(rss).toBeDefined()
    if (rss) {
      expect(navTargetOf(rss).scope).toEqual({ kind: 'rss' })
      expect(navTargetOf(rss).section).toBe('home')
    }
  })

  it('settings 深链 id 约定：settings:前缀 → 分类 id', () => {
    expect(settingsCategoryOf('settings:api-sources')).toBe('api-sources')
    expect(settingsCategoryOf('settings:mail')).toBe('mail')
    expect(settingsCategoryOf('settings:ai')).toBe('ai')
    expect(settingsCategoryOf('home')).toBeNull()
  })

  it('sourceTypeSourceOrder：九类齐全，前六位与 SourcesPage 现行 TYPE_ORDER 一致', () => {
    const order = sourceTypeSourceOrder()
    expect(order.map((m) => m.type)).toEqual([
      'rss',
      'rsshub',
      'api_source',
      'newsletter',
      'inbox',
      'obsidian',
      'bookmark',
      'clip',
      'snapshot',
    ])
    // 文案锚点：来源中心语境标签（future 消费零漂移）
    expect(order.find((m) => m.type === 'newsletter')?.label).toBe('邮件桥')
    expect(order.find((m) => m.type === 'rsshub')?.label).toBe('RSSHub 路由')
  })
})
