/** N057 — 代码块独立阅读页（长代码 > 20 行 → 「展开代码」入口 →
 * 独立面板：行号栏 + 面板内搜索跳转 + 横向滚动保持 + 复制空白原样；
 * 关闭还原滚动位置并归还焦点）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { countCodeLines, findCodeMatches, isMeaningfulQuery } from '../lib/code-reader'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '代码文章',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-24T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: '<p>正文</p>',
    contentText: '正文',
    ...overrides,
  } as unknown as EntryDetail
}

function renderArticle(contentHtml: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <div>
        {/* Reader 结构契约：.lumi-reader-article 的父级是滚动容器 */}
        <div>
          <div className="lumi-reader-article">
            <ArticleContent detail={detail({ contentHtml })} />
          </div>
        </div>
      </div>
    </QueryClientProvider>,
  )
}

function scroller(): HTMLElement {
  return document.querySelector('.lumi-reader-article')!.parentElement!
}

function stubScrollerLayout(node: HTMLElement, scrollTop: number) {
  Object.defineProperty(node, 'scrollHeight', { value: 4000, configurable: true })
  Object.defineProperty(node, 'clientHeight', { value: 600, configurable: true })
  Object.defineProperty(node, 'scrollTop', { value: scrollTop, writable: true, configurable: true })
}

const LONG_CODE = Array.from({ length: 25 }, (_, i) =>
  i === 4 ? 'const alpha = 1' : i === 14 ? 'const alpha = 2' : i === 9 ? '  indented()' : `line ${i + 1}`,
).join('\n')

const CONTENT = `<p>开头段落</p><pre><code>${LONG_CODE}</code></pre><pre><code>short = 1</code></pre>`

beforeEach(() => {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS, readerCodeHighlight: 'off' } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  const nav = window.navigator as unknown as Record<string, unknown>
  delete nav.clipboard
})

describe('N057 代码块独立阅读页', () => {
  it('超过 20 行的代码块出现「展开代码」入口；短代码块没有', async () => {
    renderArticle(CONTENT)
    const buttons = await screen.findAllByRole('button', { name: '展开代码' })
    expect(buttons).toHaveLength(1)
    // 幂等：装饰重复执行不叠加
    await waitFor(() => expect(buttons[0]!.dataset.lumiCodeExpand).toBe('true'))
  })

  it('点击打开独立阅读页：行号栏 1..25、源码行与行数标注；Esc 关闭还原滚动 + 焦点归还', async () => {
    renderArticle(CONTENT)
    stubScrollerLayout(scroller(), 444)
    fireEvent.click(await screen.findByRole('button', { name: '展开代码' }))

    const dialog = await screen.findByRole('dialog', { name: '代码查看' })
    const host = dialog.querySelector('[data-testid="code-reader-host"]')
    expect(host).not.toBeNull()
    expect(host!.getAttribute('data-code-lines')).toBe('25')
    // 行号栏：1..25（gutter 与文档序一致）
    const numbers = Array.from(dialog.querySelectorAll('.lumi-code-gutter')).map(
      (el) => el.textContent,
    )
    expect(numbers).toHaveLength(25)
    expect(numbers[0]).toBe('1')
    expect(numbers[24]).toBe('25')
    // 源码行原样展示（含缩进行的空白）
    const line10 = dialog.querySelector('[data-line="10"]')
    expect(line10!.textContent).toContain('  indented()')

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: '代码查看' })).toBeNull()
    })
    expect(scroller().scrollTop).toBe(444)
    expect(document.activeElement).toBe(await screen.findByRole('button', { name: '展开代码' }))
  })

  it('面板内搜索：命中计数 n/m、下一处跳转、无结果诚实显示', async () => {
    renderArticle(CONTENT)
    fireEvent.click(await screen.findByRole('button', { name: '展开代码' }))
    const dialog = await screen.findByRole('dialog', { name: '代码查看' })
    const input = screen.getByLabelText('搜索代码') as HTMLInputElement

    // 未搜索：计数留空（不用假 0/0）
    expect(screen.getByTestId('code-reader-match-count').textContent).toBe('')

    fireEvent.change(input, { target: { value: 'alpha' } })
    expect(await screen.findByText('1/2 处命中')).toBeInTheDocument()
    // 两个匹配都有 mark；当前匹配唯一
    expect(dialog.querySelectorAll('mark.lumi-code-match')).toHaveLength(2)
    const currentMarks = dialog.querySelectorAll('mark.lumi-code-match[data-current="true"]')
    expect(currentMarks).toHaveLength(1)

    fireEvent.click(screen.getByRole('button', { name: '下一处匹配' }))
    expect(await screen.findByText('2/2 处命中')).toBeInTheDocument()
    // data-current 移到第二个匹配（第 15 行）
    const secondCurrent = dialog.querySelectorAll('mark.lumi-code-match[data-current="true"]')
    expect(secondCurrent).toHaveLength(1)
    expect(
      secondCurrent[0]!.closest('[data-line]')!.getAttribute('data-line'),
    ).toBe('15')

    fireEvent.change(input, { target: { value: '不存在的词' } })
    expect(await screen.findByText('无结果')).toBeInTheDocument()
    expect(dialog.querySelectorAll('mark.lumi-code-match')).toHaveLength(0)
  })

  it('复制按钮使用既有 code-copy 逻辑：空白原样保留、无行号污染', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(window.navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderArticle(CONTENT)
    fireEvent.click(await screen.findByRole('button', { name: '展开代码' }))
    await screen.findByRole('dialog', { name: '代码查看' })

    fireEvent.click(screen.getByRole('button', { name: '复制' }))
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    const copied = writeText.mock.calls[0]![0] as string
    // 与源 <code> 的 textContent（去结尾换行）逐字一致：缩进保留、无行号
    expect(copied).toBe(LONG_CODE)
    expect(copied).toContain('\n  indented()\n')
    expect(copied).not.toMatch(/^\s*\d+\s/m)
  })
})

describe('N057 code-reader 纯辅助', () => {
  it('countCodeLines：结尾换行不计一行；空文本 0 行', () => {
    expect(countCodeLines('a\nb\nc')).toBe(3)
    expect(countCodeLines('a\nb\nc\n')).toBe(3)
    expect(countCodeLines('')).toBe(0)
    expect(countCodeLines('\n')).toBe(0)
    expect(countCodeLines('\n\n')).toBe(2) // 中间空行是真实行
  })

  it('findCodeMatches：大小写不敏感、同多行多匹配、文档序；空查询 []', () => {
    const lines = ['const Alpha = 1', 'alpha()', 'const ALPHA2 = 3']
    expect(findCodeMatches(lines, 'alpha')).toEqual([
      { line: 0, start: 6, end: 11 },
      { line: 1, start: 0, end: 5 },
      { line: 2, start: 6, end: 11 },
    ])
    // 同行重复匹配
    expect(findCodeMatches(['a a a'], 'a')).toEqual([
      { line: 0, start: 0, end: 1 },
      { line: 0, start: 2, end: 3 },
      { line: 0, start: 4, end: 5 },
    ])
    expect(findCodeMatches(lines, '')).toEqual([])
    expect(findCodeMatches(lines, '  ')).toEqual([])
    expect(isMeaningfulQuery('  ')).toBe(false)
  })
})
