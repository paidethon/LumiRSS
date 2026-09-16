/** 代码块复制装饰回归（pool #04）：幂等装饰、复制内容干净（无按钮
 * 文本污染、结尾换行剥离）、成功/失败都有可见反馈并复位。 */

import { describe, expect, it, vi } from 'vitest'
import { decorateCodeCopyButtons } from '../lib/code-copy'

function mount(html: string): HTMLElement {
  const container = document.createElement('div')
  container.innerHTML = html
  document.body.appendChild(container)
  return container
}

const SCHEDULE = (fn: () => void) => fn()

/** 手动 flush 的调度器：先让反馈可见，测试末尾再还原。 */
function makeDeferredSchedule() {
  const pending: (() => void)[] = []
  return {
    schedule: (fn: () => void) => {
      pending.push(fn)
    },
    flush: () => {
      while (pending.length > 0) pending.shift()!()
    },
  }
}

describe('decorateCodeCopyButtons', () => {
  it('给每个非空 <pre> 追加复制按钮，幂等（重复装饰不叠加）', () => {
    const container = mount(
      '<pre><code>const a = 1</code></pre><pre><code>let b = 2</code></pre>',
    )
    decorateCodeCopyButtons(container, { scheduleRevert: SCHEDULE })
    expect(container.querySelectorAll('.code-copy-btn').length).toBe(2)
    decorateCodeCopyButtons(container, { scheduleRevert: SCHEDULE })
    expect(container.querySelectorAll('.code-copy-btn').length).toBe(2)
    container.remove()
  })

  it('点击复制 <code> 文本（按钮不注入自身文本）', async () => {
    const container = mount('<pre><code>console.log("hi")\n</code></pre>')
    const writes: string[] = []
    decorateCodeCopyButtons(container, {
      writeText: async (text) => {
        writes.push(text)
      },
      scheduleRevert: SCHEDULE,
    })
    const button = container.querySelector('.code-copy-btn') as HTMLButtonElement
    button.click()
    await vi.waitFor(() => expect(writes).toEqual(['console.log("hi")']))
    container.remove()
  })

  it('复制成功 → 「已复制 ✓」反馈并复位', async () => {
    const container = mount('<pre><code>x = 1</code></pre>')
    const writes: string[] = []
    const timer = makeDeferredSchedule()
    decorateCodeCopyButtons(container, {
      writeText: async (text) => {
        writes.push(text)
      },
      scheduleRevert: timer.schedule,
    })
    const button = container.querySelector('.code-copy-btn') as HTMLButtonElement
    button.click()
    await vi.waitFor(() => expect(button.textContent).toBe('已复制 ✓'))
    expect(writes).toEqual(['x = 1'])
    timer.flush()
    expect(button.textContent).toBe('复制')
    expect(button.disabled).toBe(false)
    container.remove()
  })

  it('复制失败 → 「复制失败」反馈（不假装成功）', async () => {
    const container = mount('<pre><code>y = 2</code></pre>')
    const timer = makeDeferredSchedule()
    decorateCodeCopyButtons(container, {
      writeText: async () => {
        throw new Error('denied')
      },
      scheduleRevert: timer.schedule,
    })
    const button = container.querySelector('.code-copy-btn') as HTMLButtonElement
    button.click()
    await vi.waitFor(() => expect(button.textContent).toBe('复制失败'))
    timer.flush()
    expect(button.textContent).toBe('复制')
    container.remove()
  })

  it('空代码块不加按钮', () => {
    const container = mount('<pre><code>   </code></pre>')
    decorateCodeCopyButtons(container, { scheduleRevert: SCHEDULE })
    expect(container.querySelectorAll('.code-copy-btn').length).toBe(0)
    container.remove()
  })
})
