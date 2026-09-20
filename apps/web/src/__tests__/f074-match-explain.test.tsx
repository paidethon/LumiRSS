/** F074 命中解释 — 徽标渲染自 matchedFields（中文标签）、popover 内容
 * 与数据一致（字段+命中词+新鲜度）、无百分比（负向）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  explainMatch,
  indexFreshnessLabel,
  MATCH_FIELD_LABELS,
} from '../lib/search-explain'
import { MatchExplainBadges } from '../components/MatchExplain'

const ITEM = {
  title: 'LumiRSS 发布 1.0',
  feedTitle: '开源周刊',
  author: '张三',
  snippet: '…阅读器 alpha 功能上线…',
  matchedFields: ['title', 'feed', 'author', 'content'],
}

describe('F074 explainMatch 纯函数', () => {
  it('F074: 字段中文标签映射 + 各字段命中词推导', () => {
    expect(MATCH_FIELD_LABELS.title).toBe('标题')
    expect(MATCH_FIELD_LABELS.content).toBe('正文')
    const result = explainMatch(ITEM, ['LumiRSS', 'alpha', '张三'])
    const byField = Object.fromEntries(result.map((r) => [r.field, r]))
    expect(byField.title?.terms).toEqual(['LumiRSS'])
    expect(byField.author?.terms).toEqual(['张三'])
    // 正文以 snippet 为可见证据：'alpha' 在 snippet 中
    expect(byField.content?.terms).toEqual(['alpha'])
    // feed 字段无命中词（'开源周刊' 不在查询里）→ 该字段被诚实略去
    expect(byField.feed).toBeUndefined()
  })

  it('F074: 新鲜度文案（分钟/小时/未知）', () => {
    const now = Date.parse('2026-09-19T12:00:00Z')
    expect(indexFreshnessLabel('2026-09-19T11:50:00Z', now)).toBe('索引于 10 分钟前')
    expect(indexFreshnessLabel('2026-09-19T09:00:00Z', now)).toBe('索引于 3 小时前')
    expect(indexFreshnessLabel(null, now)).toBeNull()
    expect(indexFreshnessLabel('not-a-date', now)).toBeNull()
  })
})

describe('F074 徽标与 popover', () => {
  it('F074: 徽标自 matchedFields 渲染；popover 列出字段/命中词/新鲜度/单腿提示；无百分比', async () => {
    render(
      <MatchExplainBadges
        item={ITEM}
        terms={['LumiRSS', 'alpha', '张三']}
        lastSyncedAt={new Date(Date.now() - 10 * 60000).toISOString()}
        libraryError="库搜索暂不可用"
      />,
    )
    // 徽标自 matchedFields 渲染（中文标签）
    expect(screen.getByText('标题')).toBeInTheDocument()
    expect(screen.getByText('作者')).toBeInTheDocument()
    expect(screen.getByText('正文')).toBeInTheDocument()

    // popover：字段+命中词 一致、新鲜度、单腿降级提示
    fireEvent.click(screen.getByRole('button', { name: '为什么匹配' }))
    const dialog = screen.getByRole('dialog', { name: '命中解释' })
    expect(dialog.textContent).toContain('标题：命中 LumiRSS')
    expect(dialog.textContent).toContain('作者：命中 张三')
    expect(dialog.textContent).toContain('索引于 10 分钟前')
    expect(dialog.textContent).toContain('库搜索暂不可用')

    // 负向契约：无任何百分比（后端无分数）
    expect(document.body.textContent?.includes('%')).toBe(false)
  })

  it('F074: 无 matchedFields → 不渲染徽标（诚实）', () => {
    render(
      <MatchExplainBadges
        item={{ ...ITEM, matchedFields: [] }}
        terms={['LumiRSS']}
        lastSyncedAt={null}
      />,
    )
    expect(screen.queryByRole('button', { name: '为什么匹配' })).toBeNull()
  })
})
