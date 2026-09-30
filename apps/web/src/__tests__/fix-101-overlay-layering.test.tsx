/**
 * FIX-101 — 弹窗 / 下拉 / Toast / 抽屉层叠关系守卫（BASELINE_OK 证据）。
 *
 * 裁决依据（2026-10 R2 fx2-overlay 批次实测）：
 * - 四族浮层原语（components/ui）已全部经 Base UI Portal 挂 body，层级
 *   只经由 tokens.css 的 --lumi-z-* 令牌阶梯：dialog 50 < popover 55 <
 *   floating 60 < tooltip 70（O123 定序：对话框内触发的菜单/提示必须
 *   盖过对话框本身——popover 55 > dialog 50，tooltip 属瞬时最上层）。
 * - App 壳自挂的 VersionUpdateToast 用 dialog+1（z-[calc(var(--lumi-z-dialog)_+_1)]）
 *   站在对话框之上；CommandPalette / RecentReads / WhatsNewTour 同式。
 * - 令牌之外的手写 z-N 类只出现在 pane 内局部堆叠（sticky 表头 z-[1]、
 *   阅读浮带 z-10/20/30 等），与 body 级 portal 浮层不在同一比较上下文。
 *
 * 本守卫钉住两件事（廉价、结构性）：
 *   1. tokens.css 阶梯定序不被倒置；
 *   2. 浮层原语各自只用自己那一档令牌、无手写 z-N 类、且运行时确实
 *      portal 到 body（Portal 策略）。
 * 新增浮层若需新档位，必须先在 tokens.css 增令牌并同步更新本清单。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Dialog } from '../components/ui/Dialog'
import { Menu } from '../components/ui/Menu'
import { Popover } from '../components/ui/Popover'

const uiRoot = resolve(__dirname, '../components/ui')
const src = (f: string) => readFileSync(resolve(uiRoot, f), 'utf8')

/** 浮层原语 → 其唯一允许的层级档（tokens.css 令牌）。 */
const FLOATING_PRIMITIVES: Record<string, { token: string; label: string }> = {
  'Dialog.tsx': { token: 'z-[var(--lumi-z-dialog)]', label: 'Dialog（弹窗）' },
  'Sheet.tsx': { token: 'z-[var(--lumi-z-dialog)]', label: 'Sheet（抽屉）' },
  'Menu.tsx': { token: 'z-[var(--lumi-z-popover)]', label: 'Menu（下拉）' },
  'Popover.tsx': { token: 'z-[var(--lumi-z-popover)]', label: 'Popover（浮层）' },
  'Tooltip.tsx': { token: 'z-[var(--lumi-z-tooltip)]', label: 'Tooltip（提示）' },
}

describe('FIX-101: 层级令牌阶梯定序（tokens.css）', () => {
  it('O123 定序：dialog 50 < popover 55 < floating 60 < tooltip 70 不被倒置', () => {
    const tokens = readFileSync(resolve(__dirname, '../styles/tokens.css'), 'utf8')
    const readTier = (name: string): number => {
      const m = tokens.match(new RegExp(`--lumi-z-${name}:\\s*(\\d+)`))
      expect(m, `--lumi-z-${name} 应存在于 tokens.css`).not.toBeNull()
      return Number(m![1])
    }
    const dialog = readTier('dialog')
    const popover = readTier('popover')
    const floating = readTier('floating')
    const tooltip = readTier('tooltip')
    // 对话框内触发的菜单/提示必须盖过对话框（O123）；tooltip 瞬时最上层
    expect(popover).toBeGreaterThan(dialog)
    expect(floating).toBeGreaterThan(popover)
    expect(tooltip).toBeGreaterThan(floating)
  })
})

describe('FIX-101: 浮层原语层级档与手写 z 类', () => {
  it('每族原语只用自己那一档 --lumi-z-* 令牌', () => {
    for (const [file, { token, label }] of Object.entries(FLOATING_PRIMITIVES)) {
      const code = src(file)
      expect(code.includes(token), `${label}（${file}）应使用 ${token}`).toBe(true)
    }
  })

  it('浮层原语无手写 z-N 破档类（层级只允许经由令牌）', () => {
    // 手写 z-N（如 z-50）会绕开令牌阶梯；PaneSeparator 的 z-10 是 pane
    // 内局部堆叠（拖拽把手），不属于浮层原语，不在本清单。
    const RAW_Z = /(?:^|[\s'"`])z-\d+/
    for (const file of Object.keys(FLOATING_PRIMITIVES)) {
      const code = src(file)
      const hit = code.match(RAW_Z)
      expect(hit, `${file} 出现手写 z-N 类：${hit?.[0] ?? ''}`).toBeNull()
    }
  })
})

describe('FIX-101: Portal 策略——浮层挂 body 而非组件树内', () => {
  it('Dialog 经 Base UI Portal 渲染到 body，不在调用方容器内', () => {
    function Harness() {
      const [open, setOpen] = useState(true)
      return (
        <div data-testid="app-root">
          <Dialog open={open} onClose={() => setOpen(false)} title="层叠守卫" footer={null}>
            内容
          </Dialog>
        </div>
      )
    }
    const { container } = render(<Harness />)
    const dialog = screen.getByRole('dialog')
    expect(container.contains(dialog)).toBe(false)
    expect(document.body.contains(dialog)).toBe(true)
  })

  it('Menu 展开后面板经 Portal 挂 body', () => {
    function Harness() {
      return (
        <div data-testid="app-root">
          <Menu
            trigger={({ open, triggerProps }) => (
              <button type="button" data-testid="menu-trigger" aria-expanded={open} {...triggerProps}>
                菜单
              </button>
            )}
            items={[{ key: 'a', content: '动作 A' }]}
            onSelect={() => {}}
          />
        </div>
      )
    }
    const { container } = render(<Harness />)
    fireEvent.click(screen.getByTestId('menu-trigger'))
    const menu = screen.getByRole('menu')
    expect(container.contains(menu)).toBe(false)
    expect(document.body.contains(menu)).toBe(true)
  })

  it('Popover 展开后面板经 Portal 挂 body', () => {
    function Harness() {
      return (
        <div data-testid="app-root">
          <Popover
            trigger={({ triggerProps }) => (
              <button type="button" data-testid="pop-trigger" {...triggerProps}>
                浮层
              </button>
            )}
          >
            {() => <div>面板内容</div>}
          </Popover>
        </div>
      )
    }
    const { container } = render(<Harness />)
    fireEvent.click(screen.getByTestId('pop-trigger'))
    const panel = screen.getByText('面板内容')
    expect(container.contains(panel)).toBe(false)
    expect(document.body.contains(panel)).toBe(true)
  })
})
