/**
 * FIX-300 — Portal 浮层的主题变量作用域（BASELINE 守卫 + 行为断言）。
 *
 * 架构（既有实现核验，2026-09 R2 web12）：
 * - 主题变量（--lumi-* 颜色族）只定义在 `:root` 与 `[data-theme='dark']`
 *   （themes.css）——作用域是 documentElement；所有 Portal 浮层（Base UI
 *   Portal 与 createPortal 挂 body）都是 <html> 的后代，按继承关系必然
 *   在主题作用域内，无需变量透传；
 * - Reader 排版/配色变量（--lumi-reader-*）由 applyReaderTypography /
 *   applyAccent 挂在 documentElement.style 上——同样是全局作用域；
 * - 唯一的子树级变体选择器 [data-reader='sepia'|'warm'] 仅 Playground
 *   与测试在树内原地消费（无 portal 逃逸）；AnnotationsLayer 的批注卡
 *   portal 到正文容器内的 data-lumi-annotations-cards 节点——它是
 *   in-tree 节点，继承正文子树作用域正是其预期行为。
 *
 * 守卫：主题 token 定义不得漂移到 class 选择器（否则子树作用域会让
 * portal 丢变量）；变量挂载点必须保持 documentElement；createPortal
 * 目标限于 body（全局浮层）或既定 in-tree 节点。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Dialog } from '../components/ui/Dialog'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__') continue
      out.push(...walk(p))
    } else if (/\.(ts|tsx|css)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-300 portal 主题作用域', () => {
  it('主题 token 只定义在全局作用域选择器（:root / [data-theme] / [data-reader]）', () => {
    const themes = readFileSync(resolve(srcRoot, 'styles/themes.css'), 'utf8')
    const scopedSelectors = [':root', "[data-theme='dark']", "[data-theme='dark'] {", '[data-reader']
    // 逐块检查：每个「定义了 --lumi-* token 的块」的选择器必须是全局作用域
    for (const m of themes.matchAll(/(^|\n)([^{}\n]+)\{([^}]*)\}/g)) {
      const selector = m[2].trim()
      const body = m[3]
      if (!/--lumi-[a-z0-9-]+\s*:/.test(body)) continue
      expect(
        scopedSelectors.some((s) => selector.startsWith(s)),
        `主题 token 定义出现在非全局选择器：${selector}`,
      ).toBe(true)
    }
  })

  it('运行时变量挂载点为 documentElement（applyReaderTypography / applyAppearance）', () => {
    const src = readFileSync(resolve(srcRoot, 'store/app-settings.ts'), 'utf8')
    for (const name of ['applyReaderTypography', 'applyAppearance'] as const) {
      const fn = src.match(
        new RegExp(`export function ${name}[\\s\\S]*?\\n\\}`),
      )?.[0]
      expect(fn, name).toBeTruthy()
      expect(fn, `${name} 必须把变量挂到 documentElement`).toContain(
        'document.documentElement',
      )
      // 变量挂载不得解析到子树元素（getElementById 例外：applyAppearance
      // 管理 head 里的 custom-CSS <style> 元素，与变量作用域无关）
      expect(fn, `${name} 不得把变量改挂子树`).not.toMatch(
        /querySelector\(|ref\.current/,
      )
    }
  })

  it('createPortal 使用文件的目标仅限 body（AnnotationsLayer 的 in-tree cardsNode 例外）', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      if (!file.endsWith('.tsx')) continue
      const src = readFileSync(file, 'utf8')
      if (!src.includes('createPortal(')) continue
      const rel = file.slice(srcRoot.length + 1)
      // AnnotationsLayer 批注卡 portal 到正文容器内的 in-tree 节点
      //（cardsNode，子树作用域即其预期宿主）；其余一律 document.body。
      if (rel.endsWith('AnnotationsLayer.tsx')) {
        expect(src).toContain('cardsNode')
        continue
      }
      if (!src.includes('document.body')) offenders.push(rel)
    }
    expect(offenders).toEqual([])
  })

  it('行为断言：Base UI Dialog 的 popup 渲染在 body 子树（documentElement 作用域内）', () => {
    const { unmount } = render(
      <Dialog open onClose={() => {}} title="测试">
        内容
      </Dialog>,
    )
    const dialog = screen.getByRole('dialog', { name: '测试' })
    // popup 挂在 body 子树：与 :root/[data-theme] 变量作用域构成祖先链
    expect(document.body.contains(dialog)).toBe(true)
    // 不落入任何带 data-theme 的中间子树（主题作用域只在 <html>）
    const scoped = dialog.parentElement?.closest('[data-theme]')
    expect(scoped === null || scoped === document.documentElement).toBe(true)
    unmount()
  })
})
