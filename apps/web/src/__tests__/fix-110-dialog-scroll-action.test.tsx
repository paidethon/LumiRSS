/** FIX-110 — 弹窗内容过长时的滚动契约：单滚动容器 + 动作区恒可达。
 *
 * 裁决：BASELINE_OK。Dialog 原语（Q-P2-26 起定形）把滚动收敛为单容器：
 * Popup（max-h-[85dvh] flex-col）内唯一的 overflow-y-auto 区域是内容区，
 * footer 是其 **sibling**（shrink-0，不随内容滚动、不被裁剪）——内容再长
 * 动作区也钉在面板底部可达；Base UI modal 自带 body 滚动锁，弹窗外层
 * 不会出现第二个竞争滚动源。FIX-296 另以 scrollbar-gutter: stable 抑制
 * 内容高度变化时的横向跳动。
 *
 * 本守卫钉住 jsdom 可验证的结构契约：
 *   A. 长内容弹窗内恰有一个滚动容器，footer 不在其内（不受内容裁剪）；
 *   B. footer 动作按钮可聚焦可达（内容超长也不挤出不滚动区）；
 *   C. open 期间 body 滚动锁生效（无第二个滚动容器抢滚动）。
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Dialog } from '../components/ui/Dialog'

function Harness({ paragraphs = 60 }: { paragraphs?: number }) {
  const [open, setOpen] = useState(true)
  return (
    <Dialog
      open={open}
      onClose={() => setOpen(false)}
      title="长内容弹窗"
      footer={
        <button type="button" data-testid="dialog-apply" onClick={() => setOpen(false)}>
          应用
        </button>
      }
    >
      {Array.from({ length: paragraphs }, (_, i) => (
        <p key={i}>段落 {i + 1}</p>
      ))}
    </Dialog>
  )
}

const OVERFLOW_AUTO = /\boverflow-y-auto\b/

describe('FIX-110: 弹窗滚动容器与动作区可达', () => {
  it('A. 长内容下弹窗内恰有一个滚动容器；footer 不在其中', () => {
    render(<Harness />)
    const popup = screen.getByRole('dialog')
    const scrollables = Array.from(popup.querySelectorAll<HTMLElement>('*')).filter((el) =>
      OVERFLOW_AUTO.test(el.className),
    )
    expect(scrollables).toHaveLength(1)
    const footer = screen.getByTestId('dialog-apply')
    expect(scrollables[0]!.contains(footer)).toBe(false)
    // footer 在 shrink-0 的动作条里，动作条是 Popup 的直接子层（与滚动
    // 容器互为兄弟——内容再长也不把动作区挤出面板）
    const footerBar = footer.parentElement as HTMLElement
    expect(footerBar.className).toMatch(/shrink-0/)
    expect(footerBar.parentElement).toBe(popup)
  })

  it('B. footer 动作按钮在长内容下仍可聚焦/点击（动作区恒可达）', () => {
    render(<Harness />)
    const apply = screen.getByTestId('dialog-apply')
    apply.focus()
    expect(document.activeElement).toBe(apply)
    fireEvent.click(apply)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('C. 面板自身不滚动（唯一滚动源在内容区），滚动条宽度预留 token 在位', () => {
    render(<Harness />)
    const popup = screen.getByRole('dialog')
    // 面板 = flex-col + max-h 视口钳制，无自身 overflow（否则会出现
    // 面板/内容双滚动互抢）；高度超出只可能落在唯一的内层滚动容器。
    expect(popup.className).toMatch(/max-h-\[85dvh\]/)
    expect(popup.className).toMatch(/flex-col/)
    expect(popup.className).not.toMatch(/overflow-(y-auto|auto|y-scroll|scroll)/)
    // 内容区滚动容器：scrollbar-gutter stable（FIX-296，高度变化不横跳）
    const scrollable = Array.from(popup.querySelectorAll<HTMLElement>('*')).find((el) =>
      OVERFLOW_AUTO.test(el.className),
    )!
    expect(scrollable.className).toMatch(/\[scrollbar-gutter:stable]/)
    // 注：body 滚动锁由 Base UI modal 提供（上游职责）；jsdom 无真实
    // 布局，锁的 style 副作用不落地，此处不作断言（不谎称已验证）。
  })
})
