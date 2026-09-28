/**
 * FIX-298 — 主题初始化先于首帧（防闪白）静态 + 行为验证。
 *
 * 架构（0020 AUDIT-008 既有实现，本项核验收口）：
 * - index.html 的内联防闪烁脚本（经典 <script>，同步执行）位于
 *   `<div id="root">` 之后、`<script type="module" src="/src/main.tsx">`
 *   之前——module 脚本天然 deferred，因此 data-theme 在 React 渲染
 *   任何一帧之前就挂到 <html>（themes.css 的 [data-theme] 选择器在
 *   首个样式帧即生效，无「先亮后暗」错误主题帧）；
 * - CSP 兼容：脚本无 eval / new Function；生产 Caddyfile 以 sha256
 *   钉住该内联块（csp-hash.test.ts 守卫漂移）；
 * - 逻辑单一真源：src/lib/theme.ts resolveInitialTheme（theme.test.ts
 *   已覆盖），本测试用「真实 index.html 脚本文本」在 jsdom 里执行，
 *   保证两者不漂移。
 *
 * 边界（诚实声明）：jsdom 无法真实截图，首帧验证是结构性的——
 * 「脚本位置先于 module + 同步 setAttribute」推得首帧必有主题；真机
 * 视觉验证（错误主题帧不存在）留待 Playwright 真浏览器路径。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const webRoot = resolve(__dirname, '../..')
const html = readFileSync(resolve(webRoot, 'index.html'), 'utf8')

function inlineScriptBlocks(source: string): string[] {
  return [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
}

/** 在受控环境执行真实的 index.html 内联脚本，返回 <html> 的 data-theme。
 * storageMap 模拟 localStorage；matchMediaValue 模拟 OS 偏好。 */
function runBootstrap(
  storageMap: Record<string, string>,
  matchMediaValue: boolean,
): string | null {
  const script = inlineScriptBlocks(html)[0]
  const backing = new Map(Object.entries(storageMap))
  const fakeStorage = {
    getItem: (k: string) => (backing.has(k) ? (backing.get(k) as string) : null),
  }
  const attributes = new Map<string, string>()
  const fakeDocElement = { setAttribute: (k: string, v: string) => attributes.set(k, v) }
  const fn = new Function(
    'localStorage',
    'window',
    'document',
    script,
  )
  fn(
    fakeStorage,
    { matchMedia: () => ({ matches: matchMediaValue }) },
    { documentElement: fakeDocElement },
  )
  return attributes.get('data-theme') ?? null
}

describe('FIX-298 主题引导先于首帧', () => {
  it('内联脚本位于 module 入口之前（首帧前同步执行的结构保证）', () => {
    const inlineEnd = html.indexOf('</script>')
    const moduleStart = html.indexOf('<script type="module" src="/src/main.tsx">')
    expect(inlineEnd).toBeGreaterThan(-1)
    expect(moduleStart).toBeGreaterThan(inlineEnd)
  })

  it('脚本 CSP 兼容：无 eval / new Function（hash 钉住由 csp-hash.test 负责）', () => {
    for (const block of inlineScriptBlocks(html)) {
      expect(block).not.toMatch(/\beval\s*\(/)
      expect(block).not.toMatch(/new Function/)
    }
  })

  it.each([
    [{ 'lumirss-settings': JSON.stringify({ themeMode: 'dark' }) }, false, 'dark'],
    [{ 'lumirss-settings': JSON.stringify({ themeMode: 'light' }) }, true, 'light'],
    [{ 'lumirss-theme': 'dark' }, false, 'dark'],
    [{}, true, 'dark'],
    [{}, false, 'light'],
    [{ 'lumirss-settings': '{broken json' }, false, 'light'],
  ])('真实内联脚本执行 %j + OS暗色=%s → %s', (storage, prefersDark, expected) => {
    expect(runBootstrap(storage as Record<string, string>, prefersDark)).toBe(expected)
  })
})
