/** FIX-269 — 代码高亮异步结果不写旧文章节点（文章代次校验验证）。
 *
 * 现状核实（诚实基线）：highlightCodeBlocks 只改写【每次管线新建的
 * inert DOM】，输出是字符串；ArticleContent 的管线 effect 以 effect
 * cleanup（cancelled 标志）作代次守卫——换文章/换设置即作废挂起结果。
 * 本文件把该契约钉进回归：A（代码 + KaTeX 标记，管线慢）切到 B（纯
 * 文本，管线快）后，等 A 的慢管线真正结算，B 的 DOM 必须原样——
 * 若代次守卫失效，A 的高亮输出会覆盖 B（守卫回归成立）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { clearArticleHtmlCaches, renderArticleHtmlCached } from '../lib/article-pipeline'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

/** A：代码块（触发 shiki 异步高亮）+ KaTeX 标记（额外动态加载，保证
 * A 的管线结算晚于 B）。 */
const A_HTML =
  '<p>A 的引言 $x^2$</p>' +
  '<pre><code class="language-js">const secretA = "A_CODE_MARKER"\n</code></pre>'
const B_HTML = '<p>B_UNIQUE_PARAGRAPH</p>'

/** 与 ArticleContent effect 逐字一致的管线选项（缓存 key 去重用）。 */
const OPTS = {
  conversion: 'off',
  bionic: false,
  codeTheme: 'github-light',
  footnotes: true,
  math: true,
  firstImageFullBleed: false,
  codeLineNumbers: false,
  stripFixedMedia: true,
} as const

function detail(entryRef: string, html: string): EntryDetail {
  return {
    entryRef,
    title: entryRef,
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: html,
    contentText: '正文',
  } as unknown as EntryDetail
}

beforeEach(() => {
  localStorage.clear()
  clearArticleHtmlCaches()
  useAppSettings.setState({
    settings: {
      ...DEFAULT_APP_SETTINGS,
      readerCodeHighlight: 'auto',
      readerCodeTheme: 'github-light',
      readerChineseConversion: 'off',
      readerBionic: false,
      readerFirstImageFullBleed: false,
      readerCodeLineNumbers: false,
      readerStripFixedMedia: true,
    },
  })
})

describe('FIX-269：慢高亮结果不落进换篇后的正文', () => {
  it('A → B 切换后，A 的管线结算不覆盖 B（代次守卫）', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = (detail: EntryDetail) => (
      <QueryClientProvider client={qc}>
        <ArticleContent detail={detail} />
      </QueryClientProvider>
    )
    const view = render(wrapper(detail('e1.a', A_HTML)))

    // 组件 effect 已发起 A 的管线 promise（缓存按 key 去重，此处取得
    // 同一实例；shiki/KaTeX 首次动态加载，结算需要真实时间）。
    const pendingA = renderArticleHtmlCached(A_HTML, OPTS)

    // 立即切到 B：effect cleanup 作废 A 的挂起结果。
    view.rerender(wrapper(detail('e2.b', B_HTML)))
    await waitFor(() =>
      expect(view.container.textContent).toContain('B_UNIQUE_PARAGRAPH'),
    )

    // 等 A 的慢管线真正结算（此刻若守卫失效，setHtml(A) 已覆盖 B）。
    await pendingA
    // 再排空一轮宏任务，给任何迟到写入机会。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(view.container.textContent).toContain('B_UNIQUE_PARAGRAPH')
    expect(view.container.textContent).not.toContain('A_CODE_MARKER')
    expect(view.container.textContent).not.toContain('A 的引言')
    expect(view.container.querySelector('pre')).toBeNull()
    expect(view.container.querySelector('.lumi-shiki-code')).toBeNull()
  })
})
