/**
 * FIX-221 / FIX-227 — 管理端列表与表单基线守卫（source-level 断言）。
 *
 * FIX-221（行 key 不用数组位置）：AdminScreen 的业务列表行一律以稳定
 * 业务 id 作 key——排序/增删后行内状态仍绑定同一实体（骨架屏占位符
 * 的 key={i} 属加载态占位，不在本守卫范围）。
 *
 * FIX-227（后台刷新不覆盖编辑中表单）：QuotaDialog 只在首次打开时
 * 用服务端值填充表单（seeded 单次闸门），staleTime 内的 refetch /
 * 失效重取不会重置正在编辑的输入框；脏字段直到提交或放弃不被覆盖。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const admin = readFileSync(resolve(__dirname, '..', 'components/admin/AdminScreen.tsx'), 'utf-8')

describe('FIX-221: 管理端表格行 key 使用稳定业务 id', () => {
  it('成员/邀请/方案/任务/池成员行都以业务 id 为 key', () => {
    expect(admin).toMatch(/users\.data\.map\(\(user\) => \(\s*<li key=\{user\.id\}/)
    expect(admin).toMatch(/<li key=\{invite\.id\}/)
    expect(admin).toMatch(/<li key=\{scheme\.id\}/)
    expect(admin).toMatch(/tasks\.map\(\(task\) => \(\s*<li key=\{task\.name\}/)
    expect(admin).toMatch(/members\.map\(\(member\) => \(\s*<li key=\{member\.id\}/)
  })

  it('除骨架屏占位外没有按数组位置取 key 的业务行', () => {
    const mapHeads = [...admin.matchAll(/\.map\(\((\w+)(?:, (\w+))?\) =>/g)]
    for (const [, item, idx] of mapHeads) {
      if (idx === undefined) continue
      // 唯一允许的位置 key：骨架屏占位（Skeleton 加载态）
      const after = admin.slice(admin.indexOf(`, ${idx}) =>`), admin.indexOf(`, ${idx}) =>`) + 200)
      if (!/Skeleton/.test(after)) {
        expect(
          admin.includes(`key={${idx}}`),
          `${item} 列表行不得使用位置 key`,
        ).toBe(false)
      }
    }
  })
})

describe('FIX-227: 后台刷新不覆盖编辑中的额度表单', () => {
  it('QuotaDialog 以 seeded 闸门单次填充，重取不重置输入', () => {
    expect(admin).toMatch(/if \(quota\.data && !seeded\) \{[\s\S]{0,500}setSeeded\(true\)/)
    expect(admin).toMatch(/staleTime: 5_000/)
  })
})
