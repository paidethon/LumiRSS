/** FIX-106 — 菜单定位：视口边缘不被裁切；滚动/缩放后仍锚定触发器。
 *
 * 裁决：BASELINE_OK。Menu / Popover 原语把定位完全委托给 Base UI
 * Positioner（Floating UI）：portal + side/align/sideOffset + collision
 * 处理（collisionPadding=8 视口内边距）——边缘越界自动翻转/位移，滚动、
 * 窗口尺寸与缩放变化由 Floating UI 的定位循环持续重锚触发器。原语内
 * 没有任何手写 fixed/absolute 定位（旧实现 absolute right-0/top-full 的
 * 裁切缺陷在 base-ui 迁移时已移除）。
 *
 * jsdom 无真实几何，碰撞翻转与重锚无法在本环境断言——那部分属真实
 * 渲染行为，需浏览器视觉验证（如实标注，不谎称已验证）。本守卫钉住
 * jsdom 可验证的结构契约：
 *   1. 原语源码：Positioner 携 collisionPadding，无手写定位类；
 *   2. 运行时：展开后的菜单面板挂在 body 级 portal 下，Positioner
 *      由 Base UI 接管定位（inline style.position，非组件树内 absolute）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Menu } from '../components/ui/Menu'
import { Popover } from '../components/ui/Popover'

const uiRoot = resolve(__dirname, '../components/ui')
const src = (f: string) => readFileSync(resolve(uiRoot, f), 'utf8')
/** 去掉注释后的源码（doc 注释里描述旧缺陷的「absolute right-0」等词不参与断言）。 */
const code = (f: string) =>
  src(f).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

const POSITIONED_PRIMITIVES = ['Menu.tsx', 'Popover.tsx'] as const

describe('FIX-106: 定位委托 Base UI Positioner（源码契约）', () => {
  it.each(POSITIONED_PRIMITIVES)('%s 使用 Base UI Positioner 且带 collisionPadding', (file) => {
    expect(code(file)).toMatch(/<(BaseMenu|BasePopover)\.Positioner/)
    expect(code(file)).toMatch(/collisionPadding=\{\d+\}/)
  })

  it.each(POSITIONED_PRIMITIVES)('%s 无手写 fixed/absolute 定位类', (file) => {
    // 面板定位只能来自 Positioner（Floating UI）；出现 position 工具类
    // 即意味着绕开了碰撞处理（旧实现缺陷形态）。
    expect(code(file)).not.toMatch(/['"\s](?:fixed|absolute)(?:[\s'"]|$)/)
  })
})

/** 从面板元素向上找 Base UI Positioner（持 inline position 的层）。 */
function findPositioner(el: HTMLElement): HTMLElement | null {
  let node: HTMLElement | null = el
  for (let depth = 0; node !== null && depth < 5; depth += 1) {
    if (node.style.position === 'fixed') return node
    node = node.parentElement
  }
  return null
}

describe('FIX-106: 运行时——展开面板由 portal 下的 Positioner 定位', () => {
  it('Menu 展开后的面板不在调用方容器内，Positioner 持 inline 定位样式', () => {
    function Harness() {
      return (
        <Menu
          trigger={({ triggerProps }) => (
            <button type="button" data-testid="menu-trigger" {...triggerProps}>
              菜单
            </button>
          )}
          items={[{ key: 'a', content: '动作 A' }]}
          onSelect={() => {}}
        />
      )
    }
    const { container } = render(<Harness />)
    fireEvent.click(screen.getByTestId('menu-trigger'))
    const menu = screen.getByRole('menu')
    expect(container.contains(menu)).toBe(false)
    // Positioner 由 Floating UI 写 inline 定位样式（jsdom 无几何，仅断
    // 定位权归属：fixed inline 样式存在即可）
    expect(findPositioner(menu)).not.toBeNull()
  })

  it('Popover 展开后的面板同样由 portal 下的 Positioner 定位', () => {
    function Harness() {
      return (
        <Popover trigger={({ triggerProps }) => (
          <button type="button" data-testid="pop-trigger" {...triggerProps}>
            浮层
          </button>
        )}>
          {() => <div>面板内容</div>}
        </Popover>
      )
    }
    const { container } = render(<Harness />)
    fireEvent.click(screen.getByTestId('pop-trigger'))
    const panel = screen.getByText('面板内容')
    expect(container.contains(panel)).toBe(false)
    expect(findPositioner(panel)).not.toBeNull()
  })
})
