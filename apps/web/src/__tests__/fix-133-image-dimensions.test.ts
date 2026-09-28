/**
 * FIX-133 — 图片未设尺寸或占位导致阅读位置跳动。
 *
 * 布局稳定链条（逐环验证）：
 * 1. sanitize 边界保留 width/height 属性（DOMPurify html profile 默认
 *    放行，本项目 FORBID 配置不触及尺寸属性——带尺寸的图片加载前后
 *    占位不变，这是浏览器 aspect-ratio 占位的输入）；
 * 2. 展示管线（transforms / deferImages↔restoreImages /
 *    blockRemoteImages↔unblockSingleImage）只读写 src/srcset/data-*，
 *    尺寸属性全程不动；
 * 3. CSS 消费：.article-content img max-width + height:auto ——
 *    width/height 属性经 UA aspect-ratio 提示在加载前预留正确比例
 *    空间（jsdom 无布局，CSS 侧绑定 source 断言）。
 *
 * 结论（诚实边界）：管线不产生跳动；feed 完全未提供尺寸的图片没有
 * 客户端可用的元数据，属上游数据缺口（占位按钮语义见 F009/F22）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { renderArticleHtml, sanitizeArticleHtmlCached } from '../lib/article-pipeline'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { blockRemoteImages, clearRemoteImageExceptions, unblockSingleImage } from '../lib/remote-images'
import { deferImages, restoreImages } from '../lib/article-images'

const srcRoot = resolve(__dirname, '..')
const css = readFileSync(resolve(srcRoot, 'index.css'), 'utf-8')

const IMG = '<img src="https://example.com/a.png" width="640" height="360" alt="配图">'

afterEach(() => {
  clearRemoteImageExceptions()
})

describe('FIX-133: 尺寸属性全链路保留', () => {
  it('sanitize 边界保留 width/height', () => {
    const out = sanitizeArticleHtml(IMG)
    expect(out).toContain('width="640"')
    expect(out).toContain('height="360"')
  })

  it('展示管线（transforms 开）保留 width/height', async () => {
    const out = await renderArticleHtml(`<p>前</p>${IMG}`, {
      conversion: 'off',
      bionic: true,
      codeTheme: null,
      firstImageFullBleed: true,
    })
    expect(out).toContain('width="640"')
    expect(out).toContain('height="360"')
  })

  it('deferImages → restoreImages 往返保留 width/height', () => {
    const deferred = deferImages(IMG)
    expect(deferred.imageCount).toBe(1)
    expect(deferred.html).toContain('width="640"')
    expect(deferred.html).toContain('height="360"')
    const restored = restoreImages(deferred.html)
    expect(restored).toContain('width="640"')
    expect(restored).toContain('height="360"')
  })

  it('F009 拦截占位 → 单图恢复保留 width/height', () => {
    const blocked = blockRemoteImages(IMG)
    expect(blocked.blockedCount).toBe(1)
    expect(blocked.html).toContain('width="640"')
    const doc = document.createElement('div')
    doc.innerHTML = blocked.html
    const img = doc.querySelector('img')!
    unblockSingleImage(img)
    expect(img.getAttribute('src')).toBe('https://example.com/a.png')
    expect(img.getAttribute('width')).toBe('640')
    expect(img.getAttribute('height')).toBe('360')
  })

  it('sanitize 缓存路径同样保留（Reader 首帧路径）', () => {
    const out = sanitizeArticleHtmlCached(IMG)
    expect(out).toContain('width="640"')
    expect(out).toContain('height="360"')
  })
})

describe('FIX-133: CSS 消费 aspect-ratio 占位', () => {
  it('.article-content img：max-width 适配列宽 + height:auto（比例预留生效形态）', () => {
    // 行首锚定（避免命中 grayscale/hidden 等前缀更长的选择器）。
    const idx = css.indexOf('\n.article-content img {')
    expect(idx).toBeGreaterThan(-1)
    const close = css.indexOf('}', idx)
    const block = css.slice(idx, close)
    expect(block).toContain('max-width')
    expect(block).toContain('height: auto')
  })
})
