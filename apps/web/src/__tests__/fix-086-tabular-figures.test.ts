/**
 * FIX-086 — 数字配额、日期和计数在更新时不得横向跳动（等宽数字）。
 *
 * 审计结论（2026-09 R2）：阅读侧计数（ReaderHeader 未读数、FindBar 命
 * 中数、Pager 位置、剩余时间、代码行号等 10 处）已用 `tabular-nums`；
 * 管理台四处高频刷新数字此前缺失——本轮补齐（真实小缺陷）：
 * 邀请漏斗卡、容量卡、SystemRow 值列、服务健康延迟列。
 * 守卫钉定这四处管理台契约（阅读侧既有用法抽查锚点一并钉定）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcRoot = resolve(__dirname, '..')

const admin = readFileSync(resolve(srcRoot, 'components/admin/AdminScreen.tsx'), 'utf-8')

describe('FIX-086: 管理台高频刷新数字使用 tabular-nums', () => {
  it('漏斗卡与容量卡的数值行都是等宽数字', () => {
    const funnelCard = /data-testid=\{\`funnel-\$\{card\.key\}\`\}[\s\S]{0,200}?tabular-nums/.exec(admin)
    expect(funnelCard).not.toBeNull()
    const capacityCard = /data-testid=\{\`capacity-\$\{card\.key\}\`\}[\s\S]{0,200}?tabular-nums/.exec(admin)
    expect(capacityCard).not.toBeNull()
  })

  it('SystemRow 值列（存储/会话计数）与服务延迟列都是等宽数字', () => {
    const systemRow = /function SystemRow\([\s\S]{0,500}?tabular-nums/.exec(admin)
    expect(systemRow).not.toBeNull()
    const bare = admin.replace(/\/\*[\s\S]*?\*\//g, ' ')
    expect(bare).toContain('{service.latencyMs !== null && (')
    expect(bare).toContain('text-xs tabular-nums text-[var(--lumi-text-tertiary)]')
  })

  it('阅读侧既有 tabular-nums 锚点仍在（FindBar 命中数 / 代码行号）', () => {
    const findBar = readFileSync(resolve(srcRoot, 'components/ArticleFindBar.tsx'), 'utf-8')
    expect(findBar).toMatch(/aria-live="polite"[\s\S]{0,200}?tabular-nums/)
    const codeReader = readFileSync(resolve(srcRoot, 'components/CodeReaderPanel.tsx'), 'utf-8')
    expect(codeReader).toMatch(/lumi-code-gutter[\s\S]{0,200}?tabular-nums/)
  })
})
