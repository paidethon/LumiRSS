/** N066 媒体仅手动加载（按源）— lib + ArticleContent 接线（jsdom）。
 *
 * 覆盖：仅手动模式下初始 DOM 无任何会触发请求的媒体属性（src/srcset/
 * poster）；点击占位只恢复该一个元素；per-feedUrl 映射持久化（default
 * 移除键）；与 F22 deferImages 叠加时 img 不重复摘除；默认模式不受影响。
 * BFF source_overrides 无 mediaPolicy（已核实）→ 设备本地映射语义。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest"
import type { ReactNode } from 'react'
import ArticleContent from '../components/ArticleContent'
import {
  MEDIA_POLICY_STORAGE_KEY,
  deferMedia,
  decorateManualMedia,
  mediaPolicyFor,
  readMediaPolicies,
  restoreSingleMedia,
  writeMediaPolicy,
} from '../lib/media-policy'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const MEDIA_HTML = [
  '<p>开头段落。</p>',
  '<img src="https://img.example.com/a.png" srcset="https://img.example.com/a@2x.png 2x" alt="图A">',
  '<video src="https://video.example.com/b.mp4" poster="https://img.example.com/poster.jpg" controls></video>',
  '<audio src="https://audio.example.com/c.mp3" controls></audio>',
  '<video controls><source src="https://video.example.com/d.webm" type="video/webm"></video>',
  '<p>结尾段落。</p>',
].join('')

function detailFixture(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: MEDIA_HTML,
    feedUrl: 'https://feed.example.com/rss.xml',
  }
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ items: [] }), { headers: { 'content-type': 'application/json' } })) as unknown as Response) as unknown as Mock)
})

afterEach(() => {
  window.localStorage.clear()
  vi.unstubAllGlobals()
})

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

describe('media-policy 纯逻辑', () => {
  it('deferMedia：摘除 img/video/audio 的加载属性并打标记（幂等）', () => {
    const out = deferMedia(MEDIA_HTML)
    expect(out.mediaCount).toBe(4) // img + video + audio + video(source)
    const doc = new DOMParser().parseFromString(out.html, 'text/html')
    // 无任何会触发请求的属性
    for (const el of Array.from(doc.querySelectorAll('img, video, audio, source, track'))) {
      expect(el.getAttribute('src')).toBeNull()
      expect(el.getAttribute('srcset')).toBeNull()
      expect(el.getAttribute('poster')).toBeNull()
    }
    // 原地址保存在 data-*
    const img = doc.querySelector('img')!
    expect(img.getAttribute('data-lumi-media-src')).toBe('https://img.example.com/a.png')
    expect(img.getAttribute('data-lumi-media-srcset')).toBe(
      'https://img.example.com/a@2x.png 2x',
    )
    const video = doc.querySelector('video')!
    expect(video.getAttribute('data-lumi-media-src')).toBe('https://video.example.com/b.mp4')
    expect(video.getAttribute('data-lumi-media-poster')).toBe('https://img.example.com/poster.jpg')
    // 幂等：再次 defer 不变
    const again = deferMedia(out.html)
    expect(again.mediaCount).toBe(0)
  })

  it('restoreSingleMedia：只恢复该一个元素', () => {
    const { html } = deferMedia(MEDIA_HTML)
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    const videos = container.querySelectorAll('video')
    expect(videos.length).toBe(2)
    // 只恢复第一个 video
    restoreSingleMedia(videos[0]!)
    expect(videos[0]!.getAttribute('src')).toBe('https://video.example.com/b.mp4')
    expect(videos[0]!.hasAttribute('data-lumi-media')).toBe(false)
    // 其余元素仍处于 deferred（不加载）
    expect(videos[1]!.getAttribute('src')).toBeNull()
    const audio = container.querySelector('audio')!
    expect(audio.getAttribute('src')).toBeNull()
    const img = container.querySelector('img')!
    expect(img.getAttribute('src')).toBeNull()
    container.remove()
  })

  it('decorateManualMedia：deferred 媒体替换为占位按钮；点击只加载该元素', () => {
    const { html } = deferMedia(MEDIA_HTML)
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)
    const decorated = decorateManualMedia(container)
    expect(decorated).toBe(4)
    const buttons = Array.from(container.querySelectorAll('button.lumi-manual-media'))
    expect(buttons.length).toBe(4)
    // 幂等：已全部装饰，再次运行为 0
    expect(decorateManualMedia(container)).toBe(0)
    // 点击第二个占位（视频 b.mp4）→ 只恢复它
    ;(buttons[1] as HTMLButtonElement).click()
    expect(container.querySelector('video[src="https://video.example.com/b.mp4"]')).not.toBeNull()
    expect(container.querySelector('img[src]')).toBeNull()
    expect(container.querySelector('audio[src]')).toBeNull()
    container.remove()
  })

  it('per-feedUrl 映射持久化：manual 写入；default 移除键；损坏数据回退默认', () => {
    expect(mediaPolicyFor('https://feed.example.com/rss.xml')).toBe('default')
    writeMediaPolicy('https://feed.example.com/rss.xml', 'manual')
    expect(readMediaPolicies()).toEqual({ 'https://feed.example.com/rss.xml': 'manual' })
    expect(mediaPolicyFor('https://feed.example.com/rss.xml')).toBe('manual')
    // 其它源不受影响
    expect(mediaPolicyFor('https://other.example.com/rss')).toBe('default')
    // default 移除键（映射紧凑）
    writeMediaPolicy('https://feed.example.com/rss.xml', 'default')
    expect(readMediaPolicies()).toEqual({})
    // 损坏数据 → 诚实回退默认
    window.localStorage.setItem(MEDIA_POLICY_STORAGE_KEY, '{oops')
    expect(mediaPolicyFor('https://feed.example.com/rss.xml')).toBe('default')
    window.localStorage.setItem(MEDIA_POLICY_STORAGE_KEY, JSON.stringify({ 'https://x.test/f': 'weird' }))
    expect(mediaPolicyFor('https://x.test/f')).toBe('default')
  })
})

describe('ArticleContent 接线（N066）', () => {
  it('仅手动模式：初始 DOM 无 src（零请求）；点击占位只加载单个元素', () => {
    writeMediaPolicy('https://feed.example.com/rss.xml', 'manual')
    render(withProviders(<ArticleContent detail={detailFixture()} />))

    // 初始 DOM：无任何媒体 src 属性（浏览器不会发请求）
    const content = document.querySelector('.article-content') as HTMLElement
    expect(content).not.toBeNull()
    for (const el of Array.from(content.querySelectorAll('img, video, audio, source'))) {
      expect(el.getAttribute('src')).toBeNull()
      expect(el.getAttribute('srcset')).toBeNull()
      expect(el.getAttribute('poster')).toBeNull()
    }
    // 策略条显示仅手动 + 待加载数量
    expect(screen.getByTestId('media-policy-bar').textContent).toContain('仅手动')
    expect(screen.getByTestId('manual-media-count').textContent).toContain('4')

    // 点击图片占位 → 只恢复该 img
    const loadButtons = Array.from(
      content.querySelectorAll('button.lumi-manual-media'),
    ) as HTMLButtonElement[]
    expect(loadButtons.length).toBe(4)
    fireEvent.click(loadButtons[0]!)
    expect(content.querySelector('img[src="https://img.example.com/a.png"]')).not.toBeNull()
    expect(content.querySelector('video[src]')).toBeNull()
    expect(content.querySelector('audio[src]')).toBeNull()
  })

  it('默认模式：媒体原样渲染（src 保留，行为不变）', () => {
    render(withProviders(<ArticleContent detail={detailFixture()} />))
    const content = document.querySelector('.article-content') as HTMLElement
    expect(content.querySelector('img[src="https://img.example.com/a.png"]')).not.toBeNull()
    expect(content.querySelector('video[src="https://video.example.com/b.mp4"]')).not.toBeNull()
    expect(screen.getByTestId('media-policy-default').getAttribute('aria-pressed')).toBe('true')
  })

  it('切换策略写回 localStorage（per-feed 持久化）', () => {
    render(withProviders(<ArticleContent detail={detailFixture()} />))
    fireEvent.click(screen.getByTestId('media-policy-manual'))
    expect(readMediaPolicies()).toEqual({ 'https://feed.example.com/rss.xml': 'manual' })
    // 切回默认：键移除
    fireEvent.click(screen.getByTestId('media-policy-default'))
    expect(readMediaPolicies()).toEqual({})
  })

  it('与 F22 省流叠加：img 已被 deferImages 摘除时不重复计数', () => {
    writeMediaPolicy('https://feed.example.com/rss.xml', 'manual')
    useAppSettings.setState({
      settings: { ...useAppSettings.getState().settings, readerImageMode: 'hidden' },
    })
    render(withProviders(<ArticleContent detail={detailFixture()} />))
    // F22 摘掉 img（deferredImageCount=1），N066 只补 video/audio（3 个）
    expect(screen.getByTestId('manual-media-count').textContent).toContain('3')
    const content = document.querySelector('.article-content') as HTMLElement
    for (const el of Array.from(content.querySelectorAll('img, video, audio, source'))) {
      expect(el.getAttribute('src')).toBeNull()
    }
  })
})
