/**
 * FIX-131 — 正文最终渲染前的 HTML 清洗：所有文章 HTML 渲染路径共用
 * 同一安全边界（transforms → DOMPurify 唯一净化点），任何路径都不得
 * 把未清洗 HTML 送进 dangerouslySetInnerHTML。
 *
 * 覆盖四条路径（hostile payload 逐路验证惰性）：
 * 1. 原文正文：renderArticleHtml（管线 transforms 开）/ sanitizeArticleHtmlCached；
 * 2. 翻译窗格：translation-blocks applyOverlay（译文一律 textContent 注入）；
 * 3. 剪藏/原始版本：ClipsPage 使用的 safeOriginalHtml；
 * 4. AI 富文本：GptDigestSection 事实对照 bodyHtml（组件级测试）。
 *
 * fixture 中的攻击载荷是测试数据，不是真实 XSS 泄漏。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  clearArticleHtmlCaches,
  renderArticleHtml,
  sanitizeArticleHtmlCached,
} from '../lib/article-pipeline'
import { applyOverlay } from '../lib/translation-blocks'
import { safeOriginalHtml } from '../components/ClipRevisionDialog'
import { GptDigestSection } from '../components/settings/GptDigestSection'

/** 同时携带脚本注入 / 事件属性 / inline style / 表现层颜色的混合载荷。 */
const HOSTILE =
  '<p onclick="alert(1)">正文<script>alert(1)</script></p>' +
  '<img src=x onerror="alert(2)">' +
  '<a href="javascript:alert(3)">bad</a>' +
  '<iframe src="https://evil.example"></iframe>' +
  '<span style="color:red;background:yellow">styled</span>'

function expectInert(html: string): void {
  expect(html).not.toContain('<script')
  expect(html).not.toContain('<iframe')
  expect(html).not.toMatch(/onerror\s*=/i)
  expect(html).not.toMatch(/\bon[a-z]+\s*=/i)
  expect(html).not.toContain('javascript:')
  expect(html).not.toMatch(/\bstyle\s*=/i)
}

afterEach(() => {
  clearArticleHtmlCaches()
  vi.unstubAllGlobals()
})

describe('FIX-131 路径 1：原文正文（presentation pipeline）', () => {
  it('管线（transforms 全开）后 hostile payload 惰性', async () => {
    const out = await renderArticleHtml(HOSTILE, {
      conversion: 'off',
      bionic: true,
      codeTheme: null,
      footnotes: true,
      math: true,
      firstImageFullBleed: true,
      codeLineNumbers: true,
      stripFixedMedia: true,
    })
    expectInert(out)
    expect(out).toContain('正文')
  })

  it('sanitize 基线（同步首帧路径）后 hostile payload 惰性', () => {
    expectInert(sanitizeArticleHtmlCached(HOSTILE))
  })
})

describe('FIX-131 路径 2：翻译窗格（textContent 注入）', () => {
  it('hostile 译文以纯文本注入，不产生任何元素', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p data-lb-index="0">原文段落</p>'
    const hostileText = '<script>alert(1)</script><img src=x onerror="alert(2)">好译文'
    applyOverlay(root, { texts: new Map([[0, hostileText]]), mode: 'bilingual' })

    const translation = root.querySelector('.lb-translation')
    expect(translation).not.toBeNull()
    // 翻译模型输出永远不进 HTML 渲染路径：无 script / img 元素。
    expect(translation!.querySelector('script, img')).toBeNull()
    // 攻击字符串以字面文本存在（转义展示），不构成可执行标记。
    expect(translation!.textContent).toContain('<script>alert(1)</script>')
    expect(root.querySelectorAll('script').length).toBe(0)
  })
})

describe('FIX-131 路径 3：剪藏原始版本（safeOriginalHtml）', () => {
  it('hostile original.contentHtml 清洗后惰性，正文文本保留', () => {
    const out = safeOriginalHtml({ contentHtml: HOSTILE })
    expectInert(out)
    expect(out).toContain('正文')
  })

  it('非字符串 / 缺失 original → 空字符串（不抛错）', () => {
    expect(safeOriginalHtml(undefined)).toBe('')
    expect(safeOriginalHtml({ contentHtml: 42 })).toBe('')
  })
})

// ---- 路径 4：AI 富文本（GptDigestSection 事实对照 bodyHtml） ----

const ISSUE = {
  issueKey: '2026-09-28',
  status: 'published',
  title: 'AI 日报',
  note: '',
  model: 'test-model',
  createdAt: '2026-09-28T08:00:00+00:00',
  updatedAt: '2026-09-28T08:00:00+00:00',
  publishedAt: '2026-09-28T08:00:00+00:00',
  revised: false,
  meta: {},
  refs: {},
  sections: [],
  sentenceMap: [],
}

/** AI 富文本路径的 hostile bodyHtml（模拟不可信网络响应）。 */
const HOSTILE_BODY_HTML =
  '<h2>对照</h2><ul><li>事实 A<script>alert(7)</script></li>' +
  '<li onclick="alert(8)">事实 B</li></ul>' +
  '<span style="position:fixed">浮层</span>' +
  '<img src=x onerror="alert(9)">'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('FIX-131 路径 4：AI 富文本（GptDigestSection 事实对照）', () => {
  it('bodyHtml 进 DOM 前过 sanitize：hostile 载荷惰性、内容保留', async () => {
    const handler = (url: string, init?: RequestInit): Response | Promise<Response> => {
      if (url.endsWith('/gpt-digest/configs') && (!init || !init.method)) {
        return jsonResponse({
          items: [
            {
              id: 1,
              name: '默认日报',
              enabled: false,
              hour: 8,
              timezone: 'Asia/Shanghai',
              windowHours: 24,
              limitCount: 12,
              perSourceCap: 2,
              feedUrlAllow: '',
              slots: [],
              lastIssueKey: null,
              lastError: null,
              createdAt: '2026-09-18T00:00:00+00:00',
            },
          ],
        })
      }
      if (/\/configs\/\d+\/issues\/2026-09-28\/compare-facts$/.test(url) && init?.method === 'POST') {
        return jsonResponse({ title: '对照', bodyHtml: HOSTILE_BODY_HTML, promptVersion: 'v1' })
      }
      if (/\/configs\/\d+\/issues\/2026-09-28\/fact-check/.test(url)) {
        return jsonResponse({ items: [] })
      }
      if (/\/configs\/1\/issues\/2026-09-28$/.test(url)) {
        return jsonResponse({ issue: ISSUE })
      }
      if (/\/configs\/1\/issues(\?|$)/.test(url)) {
        return jsonResponse({ items: [ISSUE] })
      }
      if (/\/configs\/\d+\/pool$/.test(url) && (!init?.method || init.method === 'GET')) {
        return jsonResponse({ items: [], used: [] })
      }
      if (/\/configs\/\d+\/missing-dates/.test(url)) {
        return jsonResponse({ missing: [], existing: [] })
      }
      if (/\/configs\/\d+\/feed/.test(url)) {
        return jsonResponse({ atomPath: '/feeds/gpt-digest/x.atom' })
      }
      if (url.endsWith('/gpt-digest/feed')) {
        return jsonResponse({ atomPath: '/feeds/gpt-digest/tok.atom' })
      }
      return jsonResponse({ items: [] })
    }
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) =>
      handler(String(input), init),
    )
    vi.stubGlobal('fetch', fetchMock)

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <GptDigestSection />
      </QueryClientProvider>,
    )

    await screen.findByLabelText('选择日报配置')
    // 打开期刊所在配置的期刊列表（默认选中第一个配置即可）。
    fireEvent.click(await screen.findByRole('button', { name: '事实对照' }))

    const compare = await waitFor(() => {
      const el = document.querySelector('[data-facts-compare]')
      expect(el).not.toBeNull()
      return el as HTMLElement
    })
    // hostile 载荷全部惰性：脚本/事件属性/inline style 都不进 DOM。
    expectInert(compare.innerHTML)
    expect(compare.querySelectorAll('script').length).toBe(0)
    // 诚实内容保留（AI 输出文本可见）。
    expect(compare.textContent).toContain('事实 A')
  }, 20_000)
})
