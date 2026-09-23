/** P05 段落复制链接按钮：纯图标悬显 affordance。
 *
 * - 按钮以 aria-label「复制段落链接」为可访问名，正文流中无可见文案
 *   （原实现把「复制段落链接」裸文本常驻在每段末尾）；
 * - 点击复制 `${origin}/?entry=&para=`（para-anchor 语义不变）；
 * - 成功 → 图标变 ✓ + aria-live「链接已复制」；失败 → 诚实报错，
 *   不假装成功（同 code-copy「复制失败」既有模式）；
 * - CSS 行为（hover/focus 悬显、触屏隐藏、打印隐藏）以静态字符串断言
 *   锁定（jsdom 无布局，视觉规则只能这样验证）。 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ArticleContent from '../components/ArticleContent'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const ARTICLE_HTML =
  '<p>第一段内容足够长可以定位。</p><p>第二段也足够长。</p>'

function detail(): EntryDetail {
  return {
    entryRef: 'e9.p05',
    title: '标题',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-23T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: ARTICLE_HTML,
    contentText: '正文',
  } as unknown as EntryDetail
}

function renderArticle() {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  useReaderUi.setState({ selectedEntryRef: 'e9.p05' })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={detail()} />
    </QueryClientProvider>,
  )
}

function statusOf(button: HTMLElement): string {
  return button.querySelector('span[role="status"]')?.textContent ?? ''
}

const writeText = vi.fn()

beforeEach(() => {
  writeText.mockReset()
  writeText.mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  sessionStorage.clear()
})

describe('P05 段落复制链接按钮', () => {
  it('P05a: 按钮以 aria-label 命名，正文流中无「复制段落链接」可见文案，仅图标', async () => {
    renderArticle()
    const buttons = await screen.findAllByRole('button', { name: '复制段落链接' })
    expect(buttons.length).toBe(2)
    for (const button of buttons) {
      // 可见文案不再出现在段落流里（原实现 button.textContent 就是文案）
      expect(button.textContent).not.toContain('复制段落链接')
      expect(button.querySelector('svg')).not.toBeNull()
      expect(button.classList.contains('lumi-para-link')).toBe(true)
    }
  })

  it('P05b: 点击复制含 entry + para 锚点的链接，并显示成功反馈', async () => {
    renderArticle()
    const buttons = await screen.findAllByRole('button', { name: '复制段落链接' })
    const button = buttons[0]!
    fireEvent.click(button)
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1))
    const link = writeText.mock.calls[0]![0] as string
    expect(link).toContain('entry=e9.p05&para=')
    expect(link).toContain(window.location.origin)
    // 反馈：✓ 状态 + aria-live 文案
    await waitFor(() => expect(button.dataset.state).toBe('copied'))
    expect(statusOf(button)).toBe('链接已复制')
    // 复制的是该按钮所在段落的稳定 id
    const para = button.closest('p')
    expect(link).toContain(`para=${encodeURIComponent(para?.id ?? '')}`)
  })

  it('P05c: 剪贴板拒绝 → 诚实显示失败反馈（不静默）', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'))
    renderArticle()
    const buttons = await screen.findAllByRole('button', { name: '复制段落链接' })
    const button = buttons[0]!
    fireEvent.click(button)
    await waitFor(() => expect(button.dataset.state).toBe('error'))
    expect(statusOf(button)).toBe('复制失败')
  })

  it('P05d: index.css 静态锁定——悬显规则、键盘 focus-visible、触屏隐藏、打印隐藏', () => {
    // vitest root = apps/web（与 pnpm 脚本一致），从仓库路径读取源 CSS
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')
    // 基础规则存在（默认隐藏态）
    expect(css).toMatch(/\.lumi-para-link\s*\{[^}]*opacity:\s*0/)
    // 细指针设备：段落 hover / 焦点进入段落 → 显现
    expect(css).toMatch(
      /@media \(hover: hover\) and \(pointer: fine\)\s*\{[^{]*\.article-content > p:hover > \.lumi-para-link/,
    )
    expect(css).toMatch(
      /@media \(hover: hover\) and \(pointer: fine\)\s*\{[^{]*\.article-content > p:focus-within > \.lumi-para-link/,
    )
    // 键盘：任何设备 :focus-visible 显现
    expect(css).toMatch(/\.lumi-para-link:focus-visible\s*\{[^}]*opacity:\s*1/)
    // 触屏（粗指针）：不占布局空间
    expect(css).toMatch(
      /@media not \(\(hover: hover\) and \(pointer: fine\)\)\s*\{[^{]*\.lumi-para-link\s*\{[^}]*display:\s*none/,
    )
    // 打印隐藏（@media print 块内显式声明）
    const printBlock = css.slice(css.indexOf('@media print'))
    expect(printBlock).toMatch(/\.lumi-para-link\s*\{[^}]*display:\s*none/)
  })

  it('P05: 每个非空段落获得稳定 id（para-anchor 行为保持）', async () => {
    renderArticle()
    await screen.findAllByRole('button', { name: '复制段落链接' })
    const paragraphs = document.querySelectorAll('.article-content > p')
    expect(paragraphs[0]!.id).toMatch(/^[0-9a-f]{8}-0$/)
    expect(paragraphs[1]!.id).toMatch(/^[0-9a-f]{8}-1$/)
  })
})
