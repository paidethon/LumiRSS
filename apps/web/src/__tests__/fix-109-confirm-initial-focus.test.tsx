/** FIX-109 — 确认弹窗的初始焦点不得落在危险按钮上。
 *
 * 契约分两层钉定：
 *   1. 运行时（Dialog primitive）：初始焦点 = 面板内第一个可聚焦元素；
 *      确认弹窗的真实形态（说明文本 + footer [安全动作, 危险动作]）下，
 *      焦点必须落在安全动作（取消/返回）上，Enter 不会直接触发破坏。
 *   2. 静态审计（source-scan）：全库 `<Dialog footer>` 的首个按钮不得是
 *      variant="danger"——初始焦点由「footer 首按钮兜底」的事实性前提。
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { Dialog } from '../components/ui/Dialog'
import { Button } from '../components/ui/Button'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p))
    } else if (/\.tsx$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

/** footer={ … } 的平衡花括号区域提取（引号感知）。 */
function extractFooter(text: string, from: number): string | null {
  const fi = text.indexOf('footer={', from)
  if (fi === -1) return null
  let i = fi + 8
  let depth = 0
  let quote: string | null = null
  for (; i < text.length; i += 1) {
    const ch = text[i]
    if (quote !== null) {
      if (ch === quote) quote = null
    } else if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch
    } else if (ch === '{') {
      depth += 1
    } else if (ch === '}') {
      depth -= 1
      if (depth === 0) return text.slice(fi + 8, i)
    }
  }
  return null
}

describe('FIX-109: 确认弹窗初始焦点不落在危险按钮', () => {
  it('运行时：footer [取消(ghost), 确认删除(danger)] 的弹窗初始焦点在取消', async () => {
    render(
      <Dialog
        open
        onClose={() => {}}
        title="删除快照"
        footer={
          <>
            <Button variant="ghost">保留</Button>
            <Button variant="danger">确认删除</Button>
          </>
        }
      >
        <p>此操作不可撤销。</p>
      </Dialog>,
    )
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole('button', { name: '保留' }))
    })
    // 危险按钮存在但未持有焦点
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: '确认删除' }))
  })

  it('静态审计：全库 Dialog footer 的首个按钮不是 variant="danger"', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const raw = readFileSync(file, 'utf-8')
      const rel = relative(srcRoot, file)
      const re = /<Dialog\b/g
      let m: RegExpExecArray | null
      while ((m = re.exec(raw)) !== null) {
        const footer = extractFooter(raw, m.index)
        if (footer === null) continue
        // 首个 Button 的 variant（缺省 = secondary，非危险）
        const first = /variant="(danger|primary|secondary|ghost)"/.exec(footer)
        if (first !== null && first[1] === 'danger') {
          const line = raw.slice(0, m.index).split('\n').length
          offenders.push(`${rel}:${line}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
