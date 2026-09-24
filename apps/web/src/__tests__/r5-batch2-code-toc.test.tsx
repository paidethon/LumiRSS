/** R5 批2 测试 — F072 代码等宽字号档位 / F073 代码块行号 / F074 TOC
 * 当前章节滚动跟随高亮。
 *
 * 覆盖：设备本设置归一化与 data 标记、article pipeline 行号 transform
 * （textContent 不变 → 复制无行号污染；与 shiki 高亮共存；DOMPurify
 * 边界不变）、ArticleToc 滚动跟随（真实 Reader DOM 结构 + 几何 stub）。 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ArticleToc from '../components/ArticleToc'
import ReaderAaPanel from '../components/ReaderAaPanel'
import type { TocEntry } from '../lib/article-toc'
import {
  DEFAULT_APP_SETTINGS,
  SETTINGS_STORAGE_KEY,
  applyReaderTypography,
  normalizeSettings,
  useAppSettings,
} from '../store/app-settings'
import { clearArticleHtmlCaches, renderArticleHtml } from '../lib/article-pipeline'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  clearArticleHtmlCaches()
})

describe('F072 — 代码块等宽字号档位（设备本设置）', () => {
  it('默认中档；合法档位保留，非法值回退', () => {
    expect(normalizeSettings({}).readerCodeFontSize).toBe('m')
    expect(normalizeSettings({ readerCodeFontSize: 's' }).readerCodeFontSize).toBe('s')
    expect(normalizeSettings({ readerCodeFontSize: 'xl' }).readerCodeFontSize).toBe('m')
  })

  it('applyReaderTypography 挂 data 标记供 CSS 消费', () => {
    applyReaderTypography({ ...DEFAULT_APP_SETTINGS, readerCodeFontSize: 'l' })
    expect(document.documentElement.dataset.readerCodeFontSize).toBe('l')
  })
})

describe('F073 — article pipeline 代码块行号', () => {
  const CODE = 'const a = 1\nif (a) {\n  b()\n}'
  const RAW = `<pre><code>${CODE}</code></pre>`
  const OPTS = { conversion: 'off', bionic: false, codeTheme: null } as const

  it('开启：按行包 .lumi-code-line + data 标记（空行也有编号位）', async () => {
    const out = await renderArticleHtml(RAW, { ...OPTS, codeLineNumbers: true })
    const doc = new DOMParser().parseFromString(out, 'text/html')
    const code = doc.querySelector('pre code')
    expect(code?.hasAttribute('data-lumi-line-numbers')).toBe(true)
    expect(doc.querySelectorAll('.lumi-code-line').length).toBe(4)
  })

  it('textContent 逐字保留（复制按钮无行号污染）', async () => {
    const out = await renderArticleHtml(RAW, { ...OPTS, codeLineNumbers: true })
    const doc = new DOMParser().parseFromString(out, 'text/html')
    expect(doc.querySelector('pre code')?.textContent).toBe(CODE)
  })

  it('关闭（默认）：DOM 保持原样', async () => {
    const out = await renderArticleHtml(RAW, OPTS)
    expect(out).not.toContain('data-lumi-line-numbers')
    expect(out).not.toContain('lumi-code-line')
  })

  it('与 shiki 高亮共存：高亮 token 行同样获得行号', async () => {
    const out = await renderArticleHtml(
      '<pre><code class="language-js">const a = 1\nconst b = 2</code></pre>',
      { ...OPTS, codeTheme: 'github-light', codeLineNumbers: true },
    )
    const doc = new DOMParser().parseFromString(out, 'text/html')
    expect(doc.querySelector('code.lumi-shiki-code')).not.toBeNull()
    expect(doc.querySelectorAll('.lumi-code-line').length).toBe(2)
  })

  it('transform 不破坏 DOMPurify 边界（恶意内容仍被清洗）', async () => {
    const out = await renderArticleHtml(
      '<pre><code>ok</code></pre><img src=x onerror="alert(1)">',
      { ...OPTS, codeLineNumbers: true },
    )
    expect(out).not.toMatch(/onerror/i)
    expect(out).toContain('data-lumi-line-numbers')
  })
})

describe('ReaderAaPanel — 批2 代码排版控件（同一 settings store）', () => {
  it('F072：代码字号档位直连 store 并持久化', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('代码字号'), { target: { value: 'l' } })
    expect(useAppSettings.getState().settings.readerCodeFontSize).toBe('l')
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerCodeFontSize).toBe('l')
  })

  it('F073：代码行号开关直连 store', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.click(screen.getByRole('switch', { name: '代码行号' }))
    expect(useAppSettings.getState().settings.readerCodeLineNumbers).toBe(true)
  })
})

describe('F074 — TOC 当前章节滚动跟随高亮', () => {
  const TOC: TocEntry[] = [
    { id: 'toc-第一章', text: '第一章', level: 2 },
    { id: 'toc-第二章', text: '第二章', level: 2 },
    { id: 'toc-第三章', text: '第三章', level: 2 },
  ]

  function mountReader(): { scroller: HTMLElement } {
    const scroller = document.createElement('div')
    scroller.className = 'lumi-reader-scroll'
    const article = document.createElement('article')
    article.className = 'lumi-reader lumi-reader-article'
    const content = document.createElement('div')
    content.className = 'article-content'
    content.innerHTML = TOC.map((entry) => `<h2 id="${entry.id}">${entry.text}</h2>`).join('')
    article.appendChild(content)
    const tocMount = document.createElement('div')
    article.appendChild(tocMount)
    scroller.appendChild(article)
    document.body.appendChild(scroller)
    return { scroller }
  }

  function stubScrollerGeometry(scroller: HTMLElement): void {
    // jsdom 无布局：显式 stub 滚动几何，让「未到底」分支可达
    Object.defineProperty(scroller, 'clientHeight', { get: () => 500, configurable: true })
    Object.defineProperty(scroller, 'scrollHeight', { get: () => 2000, configurable: true })
    Object.defineProperty(scroller, 'scrollTop', { value: 0, writable: true, configurable: true })
  }

  function headingTop(id: string, top: number): void {
    vi.spyOn(document.getElementById(id)!, 'getBoundingClientRect').mockReturnValue({
      top,
    } as DOMRect)
  }

  afterEach(() => {
    cleanup()
    document.querySelectorAll('.lumi-reader-scroll').forEach((el) => el.remove())
    vi.restoreAllMocks()
  })

  it('越过跟随线的最后一个标题获得跟随高亮（aria-current + 标记）', async () => {
    const { scroller } = mountReader()
    stubScrollerGeometry(scroller)
    // 当前章 = 越过跟随线（scroller.top + 96px）的最后一个标题：
    // 第一章(-100) 与 第二章(50) 已越线，第三章(800) 未到 → 第二章
    headingTop('toc-第一章', -100)
    headingTop('toc-第二章', 50)
    headingTop('toc-第三章', 800)
    const mountPoint = document.querySelectorAll('.lumi-reader-article > div')[1]
    render(<ArticleToc toc={TOC} />, { container: mountPoint as HTMLElement })

    const buttons = screen.getAllByRole('button')
    const followBtn = buttons.find((b) => b.getAttribute('data-lumi-toc-follow') === 'true')
    expect(followBtn).toBeDefined()
    expect(followBtn).toHaveTextContent('第二章')
    expect(followBtn).toHaveAttribute('aria-current', 'true')
  })

  it('滚动触发重算（rAF 节流后更新跟随项）', async () => {
    const { scroller } = mountReader()
    stubScrollerGeometry(scroller)
    headingTop('toc-第一章', -500)
    headingTop('toc-第二章', -100)
    headingTop('toc-第三章', 400)
    const mountPoint = document.querySelectorAll('.lumi-reader-article > div')[1]
    render(<ArticleToc toc={TOC} />, { container: mountPoint as HTMLElement })
    expect(screen.getAllByRole('button').find((b) => b.getAttribute('data-lumi-toc-follow') === 'true'))
      .toHaveTextContent('第二章')

    // 滚动 300px：scroller 与全部标题的视口坐标同步上移 300
    vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue({ top: -300 } as DOMRect)
    headingTop('toc-第一章', -800)
    headingTop('toc-第二章', -400)
    headingTop('toc-第三章', -300)
    fireEvent.scroll(scroller)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.getAllByRole('button').find((b) => b.getAttribute('data-lumi-toc-follow') === 'true'))
      .toHaveTextContent('第三章')
  })

  it('章节模式激活期间跟随暂停（activeId 优先，退出后恢复）', async () => {
    const { scroller } = mountReader()
    stubScrollerGeometry(scroller)
    headingTop('toc-第一章', -100)
    headingTop('toc-第二章', 50)
    headingTop('toc-第三章', 800)
    const mountPoint = document.querySelectorAll('.lumi-reader-article > div')[1]
    render(<ArticleToc toc={TOC} />, { container: mountPoint as HTMLElement })

    // 进入章节模式：先开章节模式开关，再点第三章目录项（章节激活）
    fireEvent.click(screen.getByRole('button', { name: '章节模式' }))
    fireEvent.click(screen.getByRole('button', { name: '第三章' }))
    expect(screen.getAllByRole('button').find((b) => b.getAttribute('data-lumi-toc-follow') === 'true'))
      .toBeUndefined()
    // 章节目标保持 aria-current（既有语义，跟随不覆盖）
    expect(screen.getByRole('button', { name: '第三章' })).toHaveAttribute('aria-current', 'true')

    // Escape 退出章节 → 跟随恢复
    fireEvent.keyDown(document, { key: 'Escape' })
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.getAllByRole('button').find((b) => b.getAttribute('data-lumi-toc-follow') === 'true'))
      .toHaveTextContent('第二章')
  })
})
