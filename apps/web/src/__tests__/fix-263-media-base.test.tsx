/** FIX-263 — 图片 src/srcset 相对地址按文章原站解析。
 *
 * 正文 HTML 从原站搬运进 LumiRSS 后，相对地址（src、srcset 各候选）
 * 会被浏览器按【应用源】解析 → 请求打到 LumiRSS 自身 → 404。渲染进
 * DOM 前把每个候选按文章原站 URL 绝对化；绝对地址、data:/blob:、
 * 文内锚点、应用本地 /api/*（快照资源）一律不动。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { resolveRelativeMedia } from '../lib/article-images'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const BASE = 'https://blog.example.com/posts/hi'

describe('resolveRelativeMedia（纯函数）', () => {
  it('srcset 各候选相对文章原站解析（描述符保留）', () => {
    const { html, resolvedCount } = resolveRelativeMedia(
      '<img srcset="pic.jpg 1x, pic@2x.jpg 2x">',
      BASE,
    )
    expect(resolvedCount).toBe(1)
    expect(html).toContain(
      'srcset="https://blog.example.com/posts/pic.jpg 1x, https://blog.example.com/posts/pic@2x.jpg 2x"',
    )
  })

  it('相对 src 一并解析（按文章 URL 的目录语义，同原站浏览器行为）', () => {
    const { html, resolvedCount } = resolveRelativeMedia(
      '<img src="img/pic.png">',
      BASE,
    )
    expect(resolvedCount).toBe(1)
    expect(html).toContain('src="https://blog.example.com/posts/img/pic.png"')
  })

  it('绝对 http(s)、data:、#fragment、协议相对各有正确边界', () => {
    const input =
      '<img src="https://cdn.example.com/x.png">' +
      '<img src="data:image/png;base64,AAAA">' +
      '<img src="#frag">' +
      '<img src="//mirror.example.com/y.png">' +
      '<img srcset="https://cdn.example.com/s.png 1x, /assets/t.png 2x">'
    const { html, resolvedCount } = resolveRelativeMedia(input, BASE)
    expect(html).toContain('src="https://cdn.example.com/x.png"')
    expect(html).toContain('src="data:image/png;base64,AAAA"')
    expect(html).toContain('src="#frag"')
    expect(html).toContain('src="https://mirror.example.com/y.png"')
    expect(html).toContain('srcset="https://cdn.example.com/s.png 1x, https://blog.example.com/assets/t.png 2x"')
    // 只有真正改写了地址的 img 计数（4 个：//、srcset、img/pic 之外两条 srcset 相对）。
    expect(resolvedCount).toBe(2)
  })

  it('应用本地 /api/*（快照资源）不按原站解析', () => {
    const { html, resolvedCount } = resolveRelativeMedia(
      '<img src="/api/v1/snapshots/abc/image.png">',
      BASE,
    )
    expect(html).toContain('src="/api/v1/snapshots/abc/image.png"')
    expect(resolvedCount).toBe(0)
  })

  it('无 base / 非法 base / 无 <img：原样返回', () => {
    expect(resolveRelativeMedia('<img src="a.png">', null).resolvedCount).toBe(0)
    expect(resolveRelativeMedia('<img src="a.png">', 'not a url').resolvedCount).toBe(0)
    expect(resolveRelativeMedia('<p>没有图片</p>', BASE).html).toBe('<p>没有图片</p>')
  })
})

describe('ArticleContent 集成：DOM 内相对地址已按文章原站绝对化', () => {
  it('src 与 srcset 进入 DOM 前解析完成', () => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: 'all' },
    })
    const detail = {
      entryRef: 'e1.a',
      title: '标题',
      feedTitle: '源',
      author: null,
      url: BASE,
      publishedAt: '2026-09-18T00:00:00Z',
      read: false,
      starred: false,
      contentHtml: '<p>图</p><img src="pic.jpg" srcset="pic.jpg 1x, pic@2x.jpg 2x">',
      contentText: '图',
    } as unknown as EntryDetail
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <QueryClientProvider client={qc}>
        <ArticleContent detail={detail} />
      </QueryClientProvider>,
    )
    const img = container.querySelector('img')
    expect(img?.getAttribute('src')).toBe('https://blog.example.com/posts/pic.jpg')
    expect(img?.getAttribute('srcset')).toBe(
      'https://blog.example.com/posts/pic.jpg 1x, https://blog.example.com/posts/pic@2x.jpg 2x',
    )
  })
})
