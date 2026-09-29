/**
 * FIX-053 / FIX-058 — 管理台宽表溢出与操作列不被长用户名挤走。
 *
 * 审计结论（2026-09 R2 基线）：管理台（components/admin/）不使用原生
 * `<table>` 宽表——用户/邀请/审计均为卡片/行布局：长值渲染在
 * `truncate`（含 min-w-0 祖先约束）内，操作按钮独立成组，窄屏不发生
 * 「长用户名挤走关键操作」。移动端行为归 fix-093（抽屉/滚动锁）等
 * 既有守卫管。本文件钉定「管理台无裸表格、长值必 truncate」的结构
 * 契约；未来若引入真实表格，必须配 overflow 容器并更新本守卫。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')
const adminRoot = resolve(srcRoot, 'components/admin')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__') continue
      out.push(...walk(p))
    } else if (/\.tsx$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-053/058: 管理台长值不撑破容器、无裸宽表', () => {
  it('components/admin/ 下零原生 <table>', () => {
    const offenders: string[] = []
    for (const file of walk(adminRoot)) {
      const text = readFileSync(file, 'utf-8')
      if (/<table[\s>]/.test(text)) offenders.push(relative(srcRoot, file))
    }
    expect(offenders).toEqual([])
  })

  it('用户名/邀请名等长值渲染在 truncate 容器内（操作列不被挤走的前提）', () => {
    const admin = readFileSync(resolve(adminRoot, 'AdminScreen.tsx'), 'utf-8')
    // 成员行与邀请行的用户名/标签都是 <span className="…truncate…">。
    expect(admin).toMatch(/<span className="truncate">\{user\.username\}<\/span>/)
    expect(admin).toMatch(/<span className="truncate">\{invite\.label \?\? '未命名邀请'\}<\/span>/)
    // 成员行主标识同样 truncate。
    expect(admin).toMatch(/<span className="truncate text-\[var\(--lumi-text-primary\)\]">\{member\.username\}<\/span>/)
  })
})
