/** F30 资料溯源卡片 — 元数据展示与「未知」回退。 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ProvenanceCard from '../components/ProvenanceCard'
import type { EntryDetail } from '../api/types'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.abc',
    title: '标题',
    feedTitle: '示例源',
    author: null,
    url: null,
    publishedAt: null,
    crawledAt: null,
    read: false,
    starred: false,
    contentText: '文本',
    contentHtml: null,
    ...overrides,
  } as EntryDetail
}

describe('ProvenanceCard', () => {
  it('展示来源/作者/发布/收录/链接/内容版本；缺失诚实显示未知', () => {
    render(<ProvenanceCard detail={detail()} />)
    expect(screen.getByText('示例源')).toBeInTheDocument()
    const unknowns = screen.getAllByText('未知')
    expect(unknowns.length).toBeGreaterThanOrEqual(4) // 作者/发布/收录/链接
    expect(screen.getByText('仅纯文本')).toBeInTheDocument()
  })

  it('有数据时显示抓取与发布两个不同时刻；HTML 版本标注', () => {
    render(
      <ProvenanceCard
        detail={detail({
          author: '阿紫',
          publishedAt: '2026-09-17T10:00:00Z',
          crawledAt: '2026-09-17T10:05:00Z',
          url: 'https://blog.example.com/a',
          contentHtml: '<p>x</p>',
        })}
      />,
    )
    expect(screen.getByText('阿紫')).toBeInTheDocument()
    expect(screen.getAllByText(/^2026-09-17 \d{2}:\d{2}$/).length).toBe(2)
    expect(screen.getByText('HTML + 纯文本（正文以清洗后的 HTML 渲染）')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'https://blog.example.com/a' })
    expect(link.getAttribute('rel')).toContain('noopener')
  })
})
