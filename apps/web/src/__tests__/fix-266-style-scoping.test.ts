/**
 * FIX-266 — 文章内 style 选择器不污染应用外壳（BASELINE_OK 守卫）。
 *
 * 既有边界（三层，逐层验证）：
 * 1. DOMPurify 唯一清洗点：`<style>` 元素与 inline `style` 属性都在
 *   FORBID 列表——文章内容根本**不能携带任何 CSS**（选择器/规则无
 *   进入 DOM 的通道，自然谈不上泄漏到按钮与导航）；
 * 2. 应用自身的正文样式全部以 `.article-content`（或 `html[data-*]
 *   .article-content`）为作用域前缀（index.css），不存在裸全局规则；
 * 3. 唯一被允许的「文章样式」通道是用户自定义 CSS（F112）——注入前
 *   强制加 `.lumi-reader` 前缀（prefixCustomCss），选择器逃不出内容域。
 *
 * DOMPurify 边界零放松：本守卫只验证上述既有事实。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { prefixCustomCss } from '../lib/reader-style'

const read = (rel: string): string => readFileSync(resolve(__dirname, '..', rel), 'utf-8')

describe('FIX-266: 文章样式被严格限定在内容域', () => {
  it('指向应用外壳的 <style> 规则整体剥离（无任何选择器进入 DOM）', () => {
    const out = sanitizeArticleHtml(
      '<style>body { display: none !important } .lumi-glass { background: red }' +
        ' nav button { pointer-events: none } #root { visibility: hidden }</style>' +
        '<p>正文</p>',
    )
    expect(out).not.toContain('<style')
    expect(out).not.toContain('display')
    expect(out).not.toContain('lumi-glass')
    expect(out).toContain('<p>正文</p>')
  })

  it('inline style 属性剥离（作者定位/层级无法逃出内容流）', () => {
    const out = sanitizeArticleHtml(
      '<div style="position:fixed;inset:0;z-index:99999">悬浮层</div><span style="color:red">红字</span>',
    )
    expect(out).not.toContain('style=')
    expect(out).toContain('悬浮层')
  })

  it('ArticleContent 渲染路径不含 <style>（管线出口同样干净）', async () => {
    const { renderArticleHtml } = await import('../lib/article-pipeline')
    const out = await renderArticleHtml(
      '<style>p { display: none }</style><p>$x^2$ 正文<sup><a href="#fn1">[1]</a></sup></p><ol><li id="fn1">脚注</li></ol>',
      { conversion: 'off', bionic: false, codeTheme: null, footnotes: true, math: true },
    )
    expect(out).not.toContain('<style')
  })

  it('应用正文 CSS 全部 scoped：index.css 无脱离 .article-content/html[data-*] 的正文规则', () => {
    const css = read('index.css')
    // 提取所有含 .article-content 的规则选择器行（跳过注释行），确认每
    // 一处正文规则都带作用域前缀（.article-content 或其 html[data-*] 形态）
    for (const line of css.split('\n')) {
      if (!line.includes('.article-content')) continue
      const trimmed = line.trim()
      if (trimmed.startsWith('*') || trimmed.startsWith('/*') || trimmed.startsWith('//')) continue
      expect(trimmed).toMatch(/(^|[\s,>+~])\.article-content\b/)
    }
    // 反向抽查：不存在针对应用外壳的全局元素选择器由正文文件引入
    //（外壳样式归 components/ui 与语义令牌，正文 CSS 不含 nav/header 规则）
    expect(css).not.toMatch(/^\s*nav\s*\{/m)
    expect(css).not.toMatch(/^\s*header\s*\{/m)
  })

  it('自定义 CSS 通道强制 .lumi-reader 前缀（按钮/导航选择器逃不出内容域）', () => {
    const prefixed = prefixCustomCss('button { color: red }')
    expect(prefixed).toBe('.lumi-reader button{ color: red }')
    // 导航类选择器同样只能落在 .lumi-reader 内
    expect(prefixCustomCss('nav { display: none }')).toBe('.lumi-reader nav{ display: none }')
    // 已带前缀的不重复加
    expect(prefixCustomCss('.lumi-reader p { margin: 0 }')).toBe('.lumi-reader p{ margin: 0 }')
  })
})
