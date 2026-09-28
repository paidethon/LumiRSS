/** FIX-137 — 正文链接的打开方式与安全属性。
 *
 * 三层：
 * 1. lib/content-links：分类纯函数（external / app / anchor / passive /
 *    unsafe）与 openContentLink 动作分流；
 * 2. sanitize：javascript: 等危险协议 href 由 DOMPurify 剥离（安全底线
 *    不变，本套件回归验证）；
 * 3. ArticleContent 集成：跨源 http(s) 左键新标签（noopener,noreferrer）
 *    且装饰 target/rel；同源链接应用内路由（pushState + 路由事件，不整
 *    页跳转）；FIX-267 页内锚滚动不受影响。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import {
  classifyContentLink,
  decorateContentLinks,
  openContentLink,
} from '../lib/content-links'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { readAppRoute } from '../lib/app-route'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const APP_ORIGIN = window.location.origin

describe('classifyContentLink：分类纯函数', () => {
  const BASE = 'https://article.example.com/posts/1'

  it('纯 hash 锚 → anchor（FIX-267 页内滚动所有）', () => {
    expect(classifyContentLink('#section-1', BASE).kind).toBe('anchor')
  })

  it('跨源 http(s) → external（绝对化地址）', () => {
    const c = classifyContentLink('https://other.example.net/a?b=1', BASE)
    expect(c.kind).toBe('external')
    expect(c.href).toBe('https://other.example.net/a?b=1')
    const relative = classifyContentLink('../posts/2', BASE)
    expect(relative.kind).toBe('external')
    expect(relative.href).toBe('https://article.example.com/posts/2')
  })

  it('同源 http(s) → app（pathname+search+hash）', () => {
    const c = classifyContentLink(`${APP_ORIGIN}/admin?tab=2#x`, BASE, APP_ORIGIN)
    expect(c.kind).toBe('app')
    expect(c.appPath).toBe('/admin?tab=2#x')
  })

  it('mailto:/tel: → passive（浏览器默认行为）', () => {
    expect(classifyContentLink('mailto:a@b.c', BASE).kind).toBe('passive')
    expect(classifyContentLink('tel:+123', BASE).kind).toBe('passive')
  })

  it('javascript:/data:/vbscript:/file:/blob: 与解析失败 → unsafe', () => {
    expect(classifyContentLink('javascript:alert(1)', BASE).kind).toBe('unsafe')
    expect(classifyContentLink('data:text/html,<b>x</b>', BASE).kind).toBe('unsafe')
    expect(classifyContentLink('vbscript:x', BASE).kind).toBe('unsafe')
    expect(classifyContentLink('file:///etc/passwd', BASE).kind).toBe('unsafe')
    expect(classifyContentLink('blob:https://x/y', BASE).kind).toBe('unsafe')
  })
})

describe('openContentLink：动作分流', () => {
  it('external → 新标签 + noopener,noreferrer（注入 openExternal 只收 URL）', () => {
    const open = vi.fn()
    const taken = openContentLink(
      { kind: 'external', href: 'https://x.example/a', appPath: null },
      { openExternal: open },
    )
    expect(taken).toBe(true)
    expect(open).toHaveBeenCalledWith('https://x.example/a')
  })

  it('app → 应用内导航；unsafe → 接管且零动作；anchor/passive → 不接管', () => {
    const navigate = vi.fn()
    expect(openContentLink({ kind: 'app', href: null, appPath: '/admin' }, { navigateApp: navigate })).toBe(true)
    expect(navigate).toHaveBeenCalledWith('/admin')
    expect(openContentLink({ kind: 'unsafe', href: null, appPath: null }, { openExternal: vi.fn(), navigateApp: navigate })).toBe(true)
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(openContentLink({ kind: 'anchor', href: null, appPath: null })).toBe(false)
    expect(openContentLink({ kind: 'passive', href: null, appPath: null })).toBe(false)
  })
})

describe('sanitize：危险协议 href 剥离（安全底线回归）', () => {
  it('javascript: href 被移除，https href 保留', () => {
    const out = sanitizeArticleHtml(
      '<a href="javascript:alert(1)">坏</a><a href="https://ok.example/a">好</a>',
    )
    expect(out).not.toContain('javascript:')
    expect(out).toContain('https://ok.example/a')
  })
})

describe('decorateContentLinks：安全属性装饰', () => {
  it('external 补 target=_blank + rel；同源/锚链接不留新标签语义（幂等）', () => {
    const container = document.createElement('div')
    container.innerHTML =
      `<a href="https://other.example/a">外</a>` +
      `<a href="${APP_ORIGIN}/admin">内</a>` +
      `<a href="#s">锚</a>`
    document.body.appendChild(container)
    try {
      decorateContentLinks(container, 'https://article.example.com/a')
      decorateContentLinks(container, 'https://article.example.com/a')
      const external = container.querySelector('a[href="https://other.example/a"]')!
      expect(external.getAttribute('target')).toBe('_blank')
      expect(external.getAttribute('rel')).toBe('noopener noreferrer')
      const app = container.querySelector(`a[href="${APP_ORIGIN}/admin"]`)!
      expect(app.getAttribute('target')).toBeNull()
      expect(app.getAttribute('rel')).toBeNull()
      const anchor = container.querySelector('a[href="#s"]')!
      expect(anchor.getAttribute('target')).toBeNull()
    } finally {
      container.remove()
    }
  })
})

// ---- ArticleContent 集成 ----

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '链接文章',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-28T00:00:00Z',
    read: false,
    starred: false,
    contentText: '正文',
    ...overrides,
  } as unknown as EntryDetail
}

function renderArticle(contentHtml: string, entryUrl: string | null = null) {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={detail({ contentHtml, url: entryUrl })} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  // navigateToPath 用 pushState 改了地址：恢复初始路径，避免泄漏到后续用例
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
})

describe('ArticleContent：正文链接行为（FIX-137 集成）', () => {
  it('跨源链接：装饰 target/rel；左键 window.open 新标签，location 不变', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderArticle('<p><a href="https://other.example.net/post">站外文章</a></p>')
    const link = await screen.findByText('站外文章')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    const before = window.location.href
    fireEvent.click(link)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith(
      'https://other.example.net/post',
      '_blank',
      'noopener,noreferrer',
    )
    expect(window.location.href).toBe(before)
  })

  it('相对链接按文章原站绝对化 → external 新标签（不被误当应用内路由）', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderArticle('<p><a href="/posts/2">下一篇</a></p>', 'https://article.example.com/posts/1')
    fireEvent.click(await screen.findByText('下一篇'))
    expect(open).toHaveBeenCalledWith(
      'https://article.example.com/posts/2',
      '_blank',
      'noopener,noreferrer',
    )
  })

  it('同源链接：应用内路由（pushState + 路由事件），不整页跳转', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    let routeEvents = 0
    const listener = () => {
      routeEvents += 1
    }
    window.addEventListener('lumirss-route-change', listener)
    renderArticle(`<p><a href="${APP_ORIGIN}/admin">管理台</a></p>`)
    fireEvent.click(await screen.findByText('管理台'))
    expect(window.location.pathname).toBe('/admin')
    expect(routeEvents).toBe(1)
    expect(readAppRoute()).toBe('admin')
    expect(open).not.toHaveBeenCalled()
    window.removeEventListener('lumirss-route-change', listener)
  })

  it('mailto: 链接保留默认行为（不接管、不装饰新标签）', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    renderArticle('<p><a href="mailto:hi@example.com">写信</a></p>')
    const link = await screen.findByText('写信')
    expect(link.getAttribute('target')).toBeNull()
    expect(() => fireEvent.click(link)).not.toThrow()
    expect(open).not.toHaveBeenCalled()
  })

  it('FIX-267 页内锚滚动不受影响（分类不劫持 hash 锚）', async () => {
    const scrolled: Element[] = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this)
    }
    try {
      renderArticle(
        '<p><a href="#s1">跳转</a></p><h2 id="s1">第一节</h2>',
      )
      fireEvent.click(await screen.findByText('跳转'))
      expect(scrolled).toHaveLength(1)
      expect(scrolled[0]!.id).toBe('s1')
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })
})
