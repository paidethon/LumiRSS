/**
 * FIX-264 — 图片加载失败不重试同一坏地址（BASELINE_OK 守卫）。
 *
 * 既有实现（N039 MediaFailuresPanel + 正文图片治理族）：
 * - 检测：正文容器 capture 阶段 error 监听只做「上报」——绝不改写
 *   img.src（没有任何自动重试循环；重试的请求只可能来自用户显式动作）；
 * - 同一 src 上报在途去重（防错误风暴放大为请求风暴）；
 * - 手动重载：单项「重新加载」做一次性 cache-bust（lumi-rb），点击后
 *   按钮立即禁用——重复加载必须用户再次显式操作。
 *
 * 本守卫在 jsdom 里钉定：error → src 属性逐字不变 + 上报有界；
 * 手动重载只 bust 一次并自禁用。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import MediaFailuresPanel from '../components/MediaFailuresPanel'

const BAD_SRC = 'https://cdn.example.com/broken.png'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

/** 正文容器（面板在 document 上查询 .lumi-reader-article）。 */
function mountArticleImg(): HTMLImageElement {
  const article = document.createElement('div')
  article.className = 'lumi-reader-article'
  const img = document.createElement('img')
  img.setAttribute('src', BAD_SRC)
  article.appendChild(img)
  document.body.appendChild(article)
  return img
}

let fetchMock: ReturnType<typeof vi.fn>
let img: HTMLImageElement
let view: ReturnType<typeof render>

beforeEach(() => {
  window.localStorage.clear()
  img = mountArticleImg()
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/entries/e1/media-failures')) {
      if (init?.method === 'POST') return jsonResponse({ failures: [] })
      return jsonResponse({
        failures: [
          {
            kind: 'image',
            src: BAD_SRC,
            hitCount: 3,
            firstSeenAt: '2026-09-01T00:00:00Z',
            lastSeenAt: '2026-09-18T00:00:00Z',
          },
        ],
      })
    }
    return jsonResponse({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  view = render(withProviders(<MediaFailuresPanel entryRef="e1" />))
})

afterEach(() => {
  vi.unstubAllGlobals()
  view?.unmount()
  document.querySelector('.lumi-reader-article')?.remove()
})

describe('FIX-264: 失败图片不改写地址、不形成重试风暴', () => {
  it('img error 只触发上报：src 属性逐字不变（无自动重试）', async () => {
    fireEvent.error(img)
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).endsWith('/media-failures') && init?.method === 'POST',
        ),
      ).toHaveLength(1),
    )
    // 关键断言：失败后地址一个字节都没动（浏览器不会因 error 自发重试，
    // 应用层也绝不改写 src 制造重载）
    expect(img.getAttribute('src')).toBe(BAD_SRC)
    // 再次失败（用户刷新正文等）：仍是只上报、不改写
    fireEvent.error(img)
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).endsWith('/media-failures') && init?.method === 'POST',
        ),
      ).toHaveLength(2),
    )
    expect(img.getAttribute('src')).toBe(BAD_SRC)
  })

  it('同一 src 上报在途去重：并发 error 不放大请求', async () => {
    fireEvent.error(img)
    fireEvent.error(img)
    fireEvent.error(img)
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).endsWith('/media-failures') && init?.method === 'POST',
        ).length,
      ).toBeGreaterThanOrEqual(1),
    )
    // 在途窗口内的重复 error 全部被 inFlight 集合吞掉
    expect(
      fetchMock.mock.calls.filter(
        ([url, init]) => String(url).endsWith('/media-failures') && init?.method === 'POST',
      ),
    ).toHaveLength(1)
  })

  it('手动重载只 bust 一次（lumi-rb），按钮随即禁用', async () => {
    // 展开面板 → 失效列表出现
    fireEvent.click(screen.getByRole('button', { name: /失效附件/ }))
    await screen.findByText(BAD_SRC)
    const reload = screen.getByRole('button', { name: /重新加载/ })
    fireEvent.click(reload)
    // 恰好一次 cache-bust：src 变为带 lumi-rb 的地址，且只此一次
    await waitFor(() => expect(img.getAttribute('src')).toContain('lumi-rb='))
    expect(img.getAttribute('src').startsWith(`${BAD_SRC}?lumi-rb=`)).toBe(true)
    const bustedSrc = img.getAttribute('src')
    // 真实浏览器里 busted 地址再次失败 → error 上报 → 查询失效重拉 →
    // 重渲染后按钮呈现「已重载」禁用（jsdom 无网络加载器，手动触发）。
    fireEvent.error(img)
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([url, init]) => String(url).endsWith('/media-failures') && init?.method === 'POST',
        ),
      ).toHaveLength(1),
    )
    await waitFor(() => expect(screen.getByRole('button', { name: /已重载/ })).toBeDisabled())
    expect(screen.queryByRole('button', { name: /重新加载/ })).toBeNull()
    // bust 只发生了一次：src 仍是第一次的 busted 地址（无自动再次改写）
    expect(img.getAttribute('src')).toBe(bustedSrc)
  })
})
