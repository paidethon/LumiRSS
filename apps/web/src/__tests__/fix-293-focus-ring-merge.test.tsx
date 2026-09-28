/**
 * FIX-293 — primitives 焦点环不可被消费侧 className 覆盖。
 *
 * 背景：cx() 是顺序拼接（零依赖原则，无 tailwind-merge）。Button /
 * IconButton / Select 把消费侧 className 排在末尾，此前焦点环用
 * `focus-visible:outline-2 …` 工具类承载——消费侧传 `focus-visible:outline-none`
 * 时两者特异性相同，胜负由生成 CSS 的工具类排序决定，焦点环可能被
 * 压掉（可见键盘焦点是项目 a11y 门）。
 *
 * 修复：焦点环改由 index.css 的 `[data-lumi-focus-ring]:focus-visible`
 * 承载。该规则未分层（unlayered），按 cascade layers 语义优先于一切
 * @layer utilities 内的工具类——消费侧任何 outline-* 都不可覆盖。
 * Slider / Switch / Tabs / RadioGroup 的焦点环不经消费侧 className
 * （不接受 className 或只作用在根上），保持原样。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Button } from '../components/ui/Button'
import { IconButton } from '../components/ui/IconButton'
import { Select } from '../components/ui/Select'

const INDEX_CSS = readFileSync(resolve(__dirname, '../index.css'), 'utf8')

describe('FIX-293 焦点环合并规则（non-overridable）', () => {
  it('index.css 存在 unlayered [data-lumi-focus-ring]:focus-visible 规则', () => {
    expect(INDEX_CSS).toMatch(
      /\[data-lumi-focus-ring\]:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--lumi-focus-ring\)[^}]*\}/,
    )
  })

  it('Button 渲染 data-lumi-focus-ring 属性（消费侧 className 也移除不掉）', () => {
    render(<Button>保存</Button>)
    expect(screen.getByRole('button', { name: '保存' })).toHaveAttribute(
      'data-lumi-focus-ring',
    )
  })

  it('IconButton 渲染 data-lumi-focus-ring 属性', () => {
    render(<IconButton icon={<span />} label="关闭" />)
    expect(screen.getByRole('button', { name: '关闭' })).toHaveAttribute(
      'data-lumi-focus-ring',
    )
  })

  it('Select 渲染 data-lumi-focus-ring 属性', () => {
    render(
      <Select options={[{ value: 'a', label: 'A' }]} aria-label="选择" />,
    )
    expect(screen.getByRole('combobox', { name: '选择' })).toHaveAttribute(
      'data-lumi-focus-ring',
    )
  })

  it('消费侧传 focus-visible:outline-none 不影响焦点环载体属性', () => {
    render(
      <Button className="focus-visible:outline-none" data-testid="btn">
        保存
      </Button>,
    )
    const btn = screen.getByTestId('btn')
    expect(btn).toHaveAttribute('data-lumi-focus-ring')
    // 类串里仍含消费类，但覆盖路径已被 unlayered 规则封死
    expect(btn.className).toContain('focus-visible:outline-none')
  })

  it('接受消费侧 className 的三个 primitives 不再内联 focus-visible:outline-* 工具类', () => {
    for (const f of ['ui/Button.tsx', 'ui/IconButton.tsx', 'ui/Select.tsx']) {
      const src = readFileSync(resolve(__dirname, '../components', f), 'utf8')
      expect(src, f).not.toMatch(/focus-visible:outline-/)
    }
  })
})
