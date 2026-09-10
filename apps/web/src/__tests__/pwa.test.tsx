/** PWA 契约测试 — Phase M（spec §PWA 验收）。
 *
 * 覆盖：manifest（display/start_url/scope/icons/lang/display_override）、
 * viewport-fit=cover 且不禁用缩放、iOS apple-* 元数据齐备且与 manifest
 * 一致、theme-color 随主题同步、service worker 的安全边界（/api 永不
 * 缓存、仅内容寻址资源 cache-first、无 skipWaiting 打断）、安装引导的
 * 克制性（standalone 不弹、dismissed 永不再弹）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, fireEvent, render, screen } from '@testing-library/react'
import InstallHint from '../components/InstallHint'
import { applyTheme } from '../lib/theme'

const webRoot = join(__dirname, '..', '..')
const indexHtml = readFileSync(join(webRoot, 'index.html'), 'utf8')
const manifest = JSON.parse(
  readFileSync(join(webRoot, 'public', 'manifest.webmanifest'), 'utf8'),
) as Record<string, unknown>
const swSource = readFileSync(join(webRoot, 'public', 'sw.js'), 'utf8')

describe('manifest — 安装体验契约', () => {
  it('display=standalone（安装后无浏览器地址栏）', () => {
    expect(manifest['display']).toBe('standalone')
  })

  it('display_override 以 standalone 优先，browser 兜底（不引入 iOS 退化）', () => {
    expect(manifest['display_override']).toEqual(['standalone', 'browser'])
  })

  it('id/start_url/scope 都是 "/"（单页应用根安装）', () => {
    expect(manifest['id']).toBe('/')
    expect(manifest['start_url']).toBe('/')
    expect(manifest['scope']).toBe('/')
  })

  it('图标三件套：192/512 + maskable', () => {
    const icons = manifest['icons'] as { sizes: string; purpose?: string }[]
    expect(icons.some((i) => i.sizes === '192x192')).toBe(true)
    expect(icons.some((i) => i.sizes === '512x512' && !i.purpose)).toBe(true)
    expect(icons.some((i) => i.purpose === 'maskable' && i.sizes === '512x512')).toBe(true)
  })

  it('lang 与主题色齐备', () => {
    expect(manifest['lang']).toBe('zh-CN')
    expect(typeof manifest['theme_color']).toBe('string')
  })
})

describe('index.html — 视口与 iOS 元数据', () => {
  it('viewport-fit=cover（延伸刘海/圆角）且不禁用用户缩放（无障碍）', () => {
    const viewport = indexHtml.match(/name="viewport" content="([^"]+)"/)![1]!
    expect(viewport).toContain('viewport-fit=cover')
    expect(viewport).not.toContain('user-scalable=no')
    expect(viewport).not.toContain('maximum-scale=1')
  })

  it('iOS 专属元数据齐备且与 manifest 一致（standalone、标题、图标）', () => {
    expect(indexHtml).toContain('apple-mobile-web-app-capable')
    expect(indexHtml).toContain('apple-mobile-web-app-status-bar-style')
    expect(indexHtml).toContain('apple-mobile-web-app-title" content="LumiRSS')
    expect(indexHtml).toContain('rel="apple-touch-icon"')
    expect(indexHtml).toContain('rel="manifest"')
  })

  it('theme-color meta 存在且 applyTheme 随主题同步（dark = 深色画布）', () => {
    expect(indexHtml).toContain('name="theme-color"')
    document.head.insertAdjacentHTML(
      'beforeend',
      '<meta name="theme-color" content="#ffffff" />',
    )
    try {
      applyTheme(document.documentElement, 'dark')
      expect(
        document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
      ).toBe('#18181a')
      applyTheme(document.documentElement, 'light')
      expect(
        document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
      ).toBe('#ffffff')
    } finally {
      document.head.querySelector('meta[name="theme-color"]')?.remove()
    }
  })
})

describe('service worker — 安全与更新边界', () => {
  it('/api/* 一律绕过（认证响应/私有文章数据永不进缓存）', () => {
    expect(swSource).toContain("url.pathname.startsWith('/api/')")
    const apiGuardLine = swSource.split('\n').findIndex((l) => l.includes("startsWith('/api/')"))
    const respondWithLines = swSource
      .split('\n')
      .map((l, i) => [i, l] as const)
      .filter(([, l]) => l.includes('event.respondWith'))
    for (const [i] of respondWithLines) {
      expect(i).toBeGreaterThan(apiGuardLine)
    }
  })

  it('仅内容寻址的 /assets/* 走 cache-first', () => {
    expect(swSource).toContain("url.pathname.startsWith('/assets/')")
  })

  it('导航 network-first + 离线 shell 回退（离线不冒充会话过期）', () => {
    expect(swSource).toContain("request.mode === 'navigate'")
    expect(swSource).toContain("cache.put('/', response.clone())")
    expect(swSource).toContain("cache.match('/')")
  })

  it('无 skipWaiting（部署后旧标签页不被新 SW 打断）', () => {
    expect(swSource).not.toContain('skipWaiting()')
  })

  it('activate 清理旧版本缓存', () => {
    expect(swSource).toMatch(/caches\.keys\(\)/)
    expect(swSource).toMatch(/caches\.delete\(name\)/)
  })
})

describe('safe-area — 移动端清让', () => {
  it('CSS 变量四向 safe-area 已定义（供各容器层使用）', () => {
    const tokens = readFileSync(join(webRoot, 'src', 'index.css'), 'utf8')
    expect(tokens).toContain('--safe-top: env(safe-area-inset-top, 0px)')
    expect(tokens).toContain('--safe-bottom: env(safe-area-inset-bottom, 0px)')
  })

  it('关键容器使用 safe-area（顶栏/底栏/设置屏/登录屏）', () => {
    expect(readFileSync(join(webRoot, 'src', 'components', 'MobilePageHeader.tsx'), 'utf8')).toContain(
      'var(--safe-top)',
    )
    expect(readFileSync(join(webRoot, 'src', 'components', 'MobileTabBar.tsx'), 'utf8')).toContain(
      'var(--safe-bottom)',
    )
    expect(
      readFileSync(join(webRoot, 'src', 'components', 'MobileSettingsScreen.tsx'), 'utf8'),
    ).toContain('var(--safe-top)')
    expect(readFileSync(join(webRoot, 'src', 'components', 'LoginScreen.tsx'), 'utf8')).toContain(
      'safe-area-inset-bottom',
    )
  })
})

describe('InstallHint — 克制的安装引导', () => {
  beforeEach(() => {
    localStorage.clear()
    // 移动端视口（max-width 匹配）、非 standalone；display-mode 查询不匹配。
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockImplementation((query: string) => ({
        matches: query === '(max-width: 47.99rem)',
        addEventListener: () => {},
        removeEventListener: () => {},
      })),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  function stubUa(ua: string) {
    Object.defineProperty(window.navigator, 'userAgent', {
      value: ua,
      configurable: true,
    })
  }

  it('standalone 模式（display-mode 匹配）永不渲染', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(display-mode: standalone)',
      addEventListener: () => {},
      removeEventListener: () => {},
    })))
    stubUa('iPhone')
    render(<InstallHint />)
    expect(screen.queryByRole('complementary', { name: '安装引导' })).toBeNull()
  })

  it('iOS：延迟出现分享指引文案；关闭后永不再弹（localStorage）', async () => {
    vi.useFakeTimers()
    try {
      stubUa(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1',
      )
      const { unmount } = render(<InstallHint />)
      expect(screen.queryByRole('complementary', { name: '安装引导' })).toBeNull()
      await act(async () => {
        vi.advanceTimersByTime(3500)
      })
      expect(screen.getByRole('complementary', { name: '安装引导' })).toBeInTheDocument()
      expect(screen.getByText(/添加到主屏幕/)).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '关闭安装引导' }))
      expect(localStorage.getItem('lumirss-install-hint')).toBe('dismissed')
      unmount()

      render(<InstallHint />)
      vi.advanceTimersByTime(3500)
      expect(screen.queryByRole('complementary', { name: '安装引导' })).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
