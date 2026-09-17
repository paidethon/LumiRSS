/** F22 省流阅读 —「禁图状态不发图片请求」的行为测试。
 *
 * readerImageMode='hidden' 曾只做 CSS display:none（图片仍被完整
 * 下载）。现在 deferImages 在 HTML 进入 DOM 前摘掉 src/srcset，
 * 本文件断言：无 src 属性、有 data-lumi-src、覆盖按钮可见、点击后
 * 真实地址恢复（会发起加载）；all 模式不受影响。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { deferImages, restoreImages } from '../lib/article-images'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const ARTICLE_HTML =
  '<p>开头</p><img src="https://img.example.com/a.png" srcset="a.png 1x, a2x.png 2x" alt="图一"><p>中段</p><img src="https://img.example.com/b.png" alt="图二">'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '标题',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: ARTICLE_HTML,
    contentText: '开头 中段',
  } as unknown as EntryDetail
}

function renderWithSettings(imageMode: 'all' | 'grayscale' | 'hidden') {
  useAppSettings.setState({
    settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: imageMode },
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={detail()} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('deferImages / restoreImages（纯函数）', () => {
  it('摘除 src/srcset 并可恢复', () => {
    const { html, imageCount } = deferImages(ARTICLE_HTML)
    expect(imageCount).toBe(2)
    expect(html).not.toMatch(/\ssrc="/)
    expect(html).not.toMatch(/\ssrcset="/)
    expect(html).toContain('data-lumi-src="https://img.example.com/a.png"')
    expect(html).toContain('data-lumi-srcset=')
    const restored = restoreImages(html)
    expect(restored).toContain('src="https://img.example.com/a.png"')
    expect(restored).toContain('srcset=')
    expect(restored).not.toContain('data-lumi-image')
  })

  it('幂等：defer 两次与一次结果一致', () => {
    const once = deferImages(ARTICLE_HTML)
    const twice = deferImages(once.html)
    expect(twice.imageCount).toBe(0)
    expect(twice.html).toBe(once.html)
  })
})

describe('ArticleContent 省流模式', () => {
  it('hidden：DOM 内 img 无 src，不发图片请求；显示覆盖入口', () => {
    const { container } = renderWithSettings('hidden')
    const imgs = container.querySelectorAll('img')
    expect(imgs.length).toBe(2)
    for (const img of imgs) {
      expect(img.getAttribute('src')).toBeNull()
      expect(img.getAttribute('srcset')).toBeNull()
      expect(img.getAttribute('data-lumi-src')).toContain('img.example.com')
    }
    expect(screen.getByText(/2 张图片未加载/)).toBeInTheDocument()
  })

  it('点击「加载本文图片」后恢复真实地址', () => {
    const { container } = renderWithSettings('hidden')
    fireEvent.click(screen.getByRole('button', { name: '加载本文图片' }))
    const imgs = container.querySelectorAll('img')
    expect(imgs[0].getAttribute('src')).toBe('https://img.example.com/a.png')
    expect(imgs[0].getAttribute('srcset')).toBeTruthy()
    expect(screen.queryByText(/张图片未加载/)).not.toBeInTheDocument()
  })

  it('all 模式不做任何 defer', () => {
    const { container } = renderWithSettings('all')
    expect(container.querySelector('img')?.getAttribute('src')).toBe(
      'https://img.example.com/a.png',
    )
    expect(screen.queryByText(/张图片未加载/)).not.toBeInTheDocument()
  })

  it('F16：仅摘要（无正文 HTML）时显示诚实完整性提示', () => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: 'all' },
    })
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const detail = {
      entryRef: 'e1.b',
      title: '仅摘要条目',
      feedTitle: '源',
      author: null,
      url: 'https://blog.example.com/x',
      publishedAt: '2026-09-18T00:00:00Z',
      read: false,
      starred: false,
      contentHtml: null,
      contentText: '只有一段短摘要。',
    } as unknown as EntryDetail
    render(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={detail} />
      </QueryClientProvider>,
    )
    expect(screen.getByText(/上游 feed 未提供正文 HTML/)).toBeInTheDocument()
  })
})
