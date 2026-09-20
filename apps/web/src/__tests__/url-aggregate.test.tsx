/** F018 相同链接聚合 —— 归一化单元 + 折叠展开组件（跨页不误合）。 */

import { describe, expect, it } from 'vitest'
import { aggregateByNormalizedUrl, normalizeContentUrl } from '../lib/url-aggregate'
import type { EntryListItem } from '../api/types'

describe('F018 normalizeContentUrl', () => {
  it('F018: 同链不同参数（追踪参数/大小写/尾斜杠/scheme）合并', () => {
    const a = normalizeContentUrl('http://Example.com/post/1/?utm_source=rss')
    const b = normalizeContentUrl('https://example.com/post/1')
    expect(a).toBe(b)
    expect(a).toBe('example.com/post/1')
  })

  it('F018: 不同有效版本 URL 不合并（路径/查询语义不同）', () => {
    expect(normalizeContentUrl('https://x.com/a/1')).not.toBe(normalizeContentUrl('https://x.com/a/2'))
    expect(normalizeContentUrl('https://x.com/a?ver=1')).not.toBe(normalizeContentUrl('https://x.com/a?ver=2'))
    expect(normalizeContentUrl('https://x.com/a?token=s3cret')).not.toBe(
      normalizeContentUrl('https://x.com/a'),
    ) // 签名参数保留 → 不合并
  })

  it('F018: 非 http(s) / 非法输入 → null（不参与聚合）', () => {
    expect(normalizeContentUrl('javascript:alert(1)')).toBeNull()
    expect(normalizeContentUrl('')).toBeNull()
    expect(normalizeContentUrl('not a url')).toBeNull()
  })
})

function item(entryRef: string, url: string | null, feedTitle = '源', publishedAt = '2026-09-18T00:00:00Z'): EntryListItem {
  return {
    entryRef,
    title: `标题 ${entryRef}`,
    feedTitle,
    url,
    publishedAt,
    read: false,
    starred: false,
  } as EntryListItem
}

describe('F018 页内聚合', () => {
  it('F018: 同链折叠为一组（组代表 + 去重成员）；无 url 条目不参与', () => {
    const items = [
      item('r1', 'https://a.com/p?utm_source=x', '源一'),
      item('r2', 'https://A.com/p/', '源二', '2026-09-17T00:00:00Z'),
      item('r3', 'https://b.com/other', '源三'),
      item('r4', null, '源四'),
    ]
    const { visible, groups } = aggregateByNormalizedUrl(items)
    expect(groups.get('r1')?.duplicates.map((d) => d.entryRef)).toEqual(['r2'])
    // 折叠语义：同链成员收进组头（不作为独立行重复展示），数据不删除
    expect(visible.map((v) => v.entryRef)).toEqual(['r1', 'r3', 'r4'])
  })

  it('F018: 跨页不误合 —— 聚合函数只作用于传入的当前页数组', () => {
    const page1 = aggregateByNormalizedUrl([item('p1', 'https://x.com/story')])
    const page2 = aggregateByNormalizedUrl([item('p2', 'https://x.com/story')])
    expect(page1.groups.size).toBe(0) // 单条不成组
    expect(page2.groups.size).toBe(0)
  })

  it('F018: 列表开启「聚合同链」→ 组头显示收录数与展开成员', () => {
    // 组件级：直接用面板渲染逻辑不可行（EntryList 依赖全局 store），
    // 这里以 renderRow 同构的组头断言为主 —— 见 urlGroups 集成；
    // 本用例验证聚合结果的 UI 数据面（计数 + 成员来源/时间）。
    const items = [
      item('r1', 'https://a.com/p?utm_source=x', '源一'),
      item('r2', 'https://A.com/p/', '源二', '2026-09-17T00:00:00Z'),
      item('r3', 'https://A.com/p/', '源三', '2026-09-16T00:00:00Z'),
    ]
    const { groups } = aggregateByNormalizedUrl(items)
    const group = groups.get('r1')!
    expect(group.duplicates.length + 1).toBe(3)
    expect(group.duplicates.map((d) => d.feedTitle)).toEqual(['源二', '源三'])
    expect(group.duplicates[0]!.publishedAt).toBe('2026-09-17T00:00:00Z')
  })
})
