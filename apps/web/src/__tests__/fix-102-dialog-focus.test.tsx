/** FIX-102 — 模态框焦点契约：打开即困在面板内（focusin 不落入背景），
 * 关闭后焦点必须回到触发控件。
 *
 * 两种真实使用形态都要成立：
 *   A. 常驻挂载（open 翻 false，Dialog 留在树里）——Base UI 自带关闭还焦；
 *   B. 条件挂载（{open && <Dialog open …/>}，本应用 lazy 对话框的
 *      主流形态）——整棵 Dialog 卸载，Base UI 的还焦过渡没机会跑，
 *      焦点掉到 body。修复：原语在 open 起挂时捕获当前焦点，卸载时
 *      若焦点已丢失（activeElement 回到 body）则还焦给该元素。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { Dialog } from '../components/ui/Dialog'
import { Sheet } from '../components/ui/Sheet'

async function openAndAssertInside(getDialog: () => HTMLElement) {
  await waitFor(() => {
    const dialog = getDialog()
    expect(dialog.contains(document.activeElement)).toBe(true)
  })
}

describe('FIX-102: Dialog 焦点困住与关闭还焦', () => {
  it('A. 常驻挂载：打开→Tab 多次 focusin 不出面板；关闭→焦点回触发按钮', async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开
          </button>
          <Dialog
            open={open}
            onClose={() => setOpen(false)}
            title="确认"
            footer={
              <button type="button" onClick={() => setOpen(false)}>
                关闭
              </button>
            }
          >
            <button type="button">第一个控件</button>
            <button type="button">第二个控件</button>
          </Dialog>
        </>
      )
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: '打开' })
    trigger.focus()
    fireEvent.click(trigger)

    await openAndAssertInside(() => screen.getByRole('dialog'))

    // 连续 Tab 若干次：focusin 永不落在面板之外
    for (let i = 0; i < 6; i += 1) {
      fireEvent.keyDown(document, { key: 'Tab' })
      expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true)
    }
    expect(document.activeElement).not.toBe(document.body)

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger)
    })
  })

  it('B. 条件挂载（App lazy 形态）：卸载关闭后焦点回触发按钮，不落在 body', async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开
          </button>
          {open && (
            <Dialog
              open
              onClose={() => setOpen(false)}
              title="确认"
              footer={
                <button type="button" onClick={() => setOpen(false)}>
                  关闭
                </button>
              }
            >
              内容
            </Dialog>
          )}
        </>
      )
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: '打开' })
    trigger.focus()
    fireEvent.click(trigger)

    await openAndAssertInside(() => screen.getByRole('dialog'))

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger)
    })
  })

  it('C. Sheet（移动抽屉）条件挂载：卸载关闭后焦点回触发按钮', async () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开抽屉
          </button>
          {open && (
            <Sheet open onClose={() => setOpen(false)} label="导航">
              <button type="button" onClick={() => setOpen(false)}>
                关闭抽屉
              </button>
            </Sheet>
          )}
        </>
      )
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: '打开抽屉' })
    trigger.focus()
    fireEvent.click(trigger)

    await openAndAssertInside(() => screen.getByRole('dialog'))

    fireEvent.click(screen.getByRole('button', { name: '关闭抽屉' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
    })
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger)
    })
  })
})
