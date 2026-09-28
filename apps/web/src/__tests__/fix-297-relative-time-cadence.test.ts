/**
 * FIX-297 — 相对时间刷新节奏与展示精度对齐（BASELINE 守卫）。
 *
 * 背景（审计 2026-09 R2，web12）：本树中不存在「每秒重渲染整张卡片」
 * 的相对时间实现——相对时间（formatListTime / formatRelativeTime）全部
 * 在列表渲染时静态求值，随数据刷新（TanStack Query）更新，没有逐秒
 * ticker 驱动。全部 1s 级 setInterval 逐一核验，均与各自展示精度对齐：
 * - ReaderAaPanel.SessionDurationRow：显示「本次阅读 mm:ss」，秒级精度
 *   即展示精度，timer 只挂在面板行内（不重渲染卡片）；
 * - UndoSnackbar：撤销倒计时到期检查（剩余秒数级反馈，到期即清除）；
 * - lib/version-check：后台版本轮询（与渲染无关）。
 * 其余 setInterval 命中为命名撞车（intervalSeconds 表单值等），非计时器。
 *
 * 守卫：钉住 1s 计时器允许清单；相对时间消费组件（EntryCard / EntryRow /
 * RecentReads / RssHubTab / AdminScreen / SearchPage / AiTaskCenterPanel）
 * 内禁止出现 setInterval（新增逐秒相对时间必须显式改此守卫并按展示
 * 精度选择间隔，例如分钟级文案用 30s/60s 步进）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { formatRelativeTime } from '../lib/date-format'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__') continue
      out.push(...walk(p))
    } else if (/\.(ts|tsx)$/.test(name) && !name.endsWith('.test.ts')) {
      out.push(p)
    }
  }
  return out
}

/** 允许持有 1s 级计时器的文件（展示精度 = 1s，或与渲染无关的后台轮询） */
const TICKER_ALLOWLIST = [
  'components/ReaderAaPanel.tsx',
  'components/UndoSnackbar.tsx',
  'lib/version-check.ts',
]

/** 相对时间消费组件：禁止内置逐秒 ticker */
const RELATIVE_TIME_CONSUMERS = [
  'components/EntryCard.tsx',
  'components/EntryRow.tsx',
  'components/RecentReads.tsx',
  'components/add-source/RssHubTab.tsx',
  'components/admin/AdminScreen.tsx',
  'components/pages/SearchPage.tsx',
  'components/settings/AiTaskCenterPanel.tsx',
]

describe('FIX-297 相对时间刷新节奏守卫', () => {
  it('1s 级计时器只存在于展示精度对齐的既定三处', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const rel = file.slice(srcRoot.length + 1)
      const src = readFileSync(file, 'utf8')
      if (/setInterval\(/.test(src) && !TICKER_ALLOWLIST.includes(rel)) {
        offenders.push(rel)
      }
    }
    expect(offenders).toEqual([])
  })

  it('相对时间消费组件内无 setInterval（不做逐秒重渲染）', () => {
    for (const rel of RELATIVE_TIME_CONSUMERS) {
      const src = readFileSync(resolve(srcRoot, rel), 'utf8')
      expect(src, rel).not.toMatch(/setInterval\(/)
    }
  })

  it('展示精度契约：相对时间是分钟级文案（「N 分钟前」），无秒级档位', () => {
    // 「刚刚」(<1min) → 「N 分钟前」(<1h)：60s 内的刷新步进不会造成
    // 文案每秒变化——逐秒 ticker 对该精度毫无收益，禁用有据。
    const t0 = new Date('2026-09-28T12:00:00Z')
    expect(formatRelativeTime('2026-09-28T11:59:30Z', t0)).toBe('刚刚')
    expect(formatRelativeTime('2026-09-28T11:57:00Z', t0)).toBe('3 分钟前')
    expect(formatRelativeTime('2026-09-28T10:30:00Z', t0)).toBe('1 小时前')
  })
})
