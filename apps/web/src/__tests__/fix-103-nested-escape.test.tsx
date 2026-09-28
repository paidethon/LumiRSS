/** FIX-103 — 嵌套浮层：一次 Escape 只关闭最上层。
 *
 * 三个场景分层断言：
 *   1. 自绘浮层（RecentReads，window Escape 监听）叠在 Base UI 抽屉上
 *      ——修复前：自绘层 window bubble 监听 + Base UI document 监听互不
 *      感知，一次 Escape 同时关两层；
 *   2. 兄弟挂载的两个 Base UI Dialog（React 树不嵌套）——修复前：两者
 *      的 escapeKey: isTopmost 各自为真，一次 Escape 同时关两层；
 *   3. React 树内嵌套（Dialog 内再开 Dialog / Menu）——Base UI 内部
 *      嵌套计数本就正确，钉定为基线。
 */

import { render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Dialog } from '../components/ui/Dialog'
import { Sheet } from '../components/ui/Sheet'
import RecentReads from '../components/RecentReads'
import { resetOverlayStackForTests } from '../lib/overlay-stack'

beforeEach(() => {
  resetOverlayStackForTests()
  window.localStorage.clear()
})

function pressEscape() {
  // 真实浏览器里 Escape 派发在焦点元素上，沿 DOM 冒泡经过 document 再到
  // window——直接派发在 window 上不会触发 Base UI 挂在 document 的监听。
  const target: EventTarget =
    document.activeElement instanceof Element && document.activeElement !== document.body
      ? document.activeElement
      : document.body
  const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
  target.dispatchEvent(event)
  return event
}

describe('FIX-103: 一次 Escape 只关最上层浮层', () => {
  it('自绘「最近阅读」叠在导航抽屉上：Escape 只关面板，抽屉保持打开', async () => {
    const closeDrawer = vi.fn()
    const closePanel = vi.fn()
    render(
      <>
        <Sheet open onClose={closeDrawer} label="导航" id="fix103-drawer">
          <button type="button">抽屉内控件</button>
        </Sheet>
        <RecentReads open onClose={closePanel} />
      </>,
    )
    expect(screen.getByTestId('recent-reads-panel')).toBeInTheDocument()

    pressEscape()
    expect(closePanel).toHaveBeenCalledTimes(1)
    // 抽屉不能被同一次 Escape 击穿
    expect(closeDrawer).not.toHaveBeenCalled()
  })

  it('兄弟挂载的两个 Dialog：Escape 只关上层，下层保持打开', () => {
    const closeBase = vi.fn()
    const closeTop = vi.fn()
    render(
      <>
        <Dialog open onClose={closeBase} title="下层弹窗">
          <button type="button">下层内容</button>
        </Dialog>
        <Dialog open onClose={closeTop} title="上层确认">
          <button type="button">上层内容</button>
        </Dialog>
      </>,
    )
    pressEscape()
    expect(closeTop).toHaveBeenCalledTimes(1)
    expect(closeBase).not.toHaveBeenCalled()
  })

  it('反向叠层：Base UI Dialog 在上、自绘浮层在下 → Escape 只关 Dialog', () => {
    const closePanel = vi.fn()
    const closeDialog = vi.fn()
    render(
      <>
        <RecentReads open onClose={closePanel} />
        <Dialog open onClose={closeDialog} title="上层弹窗">
          内容
        </Dialog>
      </>,
    )
    pressEscape()
    expect(closeDialog).toHaveBeenCalledTimes(1)
    expect(closePanel).not.toHaveBeenCalled()
  })

  it('基线：React 树内嵌套 Dialog，Escape 只关最内层（Base UI 内部嵌套计数）', async () => {
    function Harness() {
      const [outer, setOuter] = useState(true)
      const [inner, setInner] = useState(true)
      return (
        <>
          <Dialog
            open={outer}
            onClose={() => setOuter(false)}
            title="外层"
            footer={<button type="button">外层按钮</button>}
          >
            {inner && (
              <Dialog open onClose={() => setInner(false)} title="内层确认">
                <button type="button">内层按钮</button>
              </Dialog>
            )}
          </Dialog>
        </>
      )
    }
    render(<Harness />)
    pressEscape()
    await waitFor(() => {
      expect(screen.getAllByRole('dialog').length).toBe(1)
    })
    // 内层已关、外层仍在
    expect(screen.getByText('外层按钮')).toBeInTheDocument()
  })
})
