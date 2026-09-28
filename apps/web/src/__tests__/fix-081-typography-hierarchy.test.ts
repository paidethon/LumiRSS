/**
 * FIX-081 — 标题 / 表单标签字号层级统一（source-level 断言）。
 *
 * 审计结论（2026-09 R2）：
 * - 分区标题（面板/分组 h2–h4）同时存在 text-xs / text-sm / text-base 三档
 *   （design-system.md §6 的字阶只承认 metadata=text-xs、controls/secondary
 *   =text-sm、heading 分层更大字号）。text-xs 的分区标题是少数派发散，统一
 *   归位到 text-sm（分区标题主流约定）；text-base 是页面级标题（更高层级），
 *   `uppercase tracking-wide` 的是 overline 眉题（独立角色），均不在此列。
 * - 表单字段标签（htmlFor/field caption）主流约定 text-xs（MailSection、
 *   AdminScreen、ApiSourcesSection 等 100+ 处）；TotpSection / AccountMenu /
 *   AiSettingsPage / SubscriptionTools 少数派用了 text-sm，归位到 text-xs。
 *   控件行标签（checkbox 行 flex gap-*）与滑杆行标题（leading-none）是不同
 *   子角色，保持 text-sm 不动。
 * - 应用标题（SidebarHeader h1）全库仅一处 text-base font-semibold，无发散。
 * - 全库无 text-[Npx] 任意字号，字阶层级全部走 Tailwind scale class。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p))
    } else if (/\.(ts|tsx|css)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

const sources = walk(srcRoot)

describe('FIX-081: 字号层级', () => {
  it('分区标题（h1–h6）不再使用 text-xs（uppercase 眉题除外）', () => {
    const offenders: string[] = []
    for (const file of sources) {
      const text = readFileSync(file, 'utf-8')
      for (const m of text.matchAll(/<h[1-6][^>]*?className="([^"]*)"/gs)) {
        const cls = m[1]
        if (cls.includes('uppercase')) continue // overline 眉题是独立角色
        if (cls.split(/\s+/).includes('text-xs')) {
          const line = text.slice(0, m.index ?? 0).split('\n').length
          offenders.push(`${relative(srcRoot, file)}:${line}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('字段标签归位主流 text-xs：四个少数派文件不再有 text-sm 的 <label>', () => {
    for (const rel of [
      'components/settings/TotpSection.tsx',
      'components/AccountMenu.tsx',
      'components/settings/AiSettingsPage.tsx',
      'components/SubscriptionTools.tsx',
    ]) {
      const text = readFileSync(resolve(srcRoot, rel), 'utf-8')
      const offenders = [...text.matchAll(/<label[^>]*?className="([^"]*)"/gs)]
        .filter((m) => m[1].split(/\s+/).includes('text-sm'))
        .map(
          (m) =>
            `${rel}:${text.slice(0, m.index ?? 0).split('\n').length}`,
        )
      expect(offenders).toEqual([])
    }
  })

  it('应用标题唯一且用字阶 class（SidebarHeader h1 = text-base）', () => {
    const text = readFileSync(
      resolve(srcRoot, 'components/SidebarHeader.tsx'),
      'utf-8',
    )
    expect(text).toMatch(/<h1 className="[^"]*text-base[^"]*"/)
  })

  it('全库不使用 text-[Npx] 任意字号', () => {
    const offenders = sources
      .filter((f) => /text-\[\d+(px|rem)\]\]/.test(readFileSync(f, 'utf-8')))
      .map((f) => relative(srcRoot, f))
    expect(offenders).toEqual([])
  })
})
