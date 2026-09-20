/** F113 —— 演示隐私遮罩（Web 层）。
 *
 * 开启：[data-privacy-text] 元素文本替换为 ▮、aria-label 清空；
 * 负向：DOM 中不残留原文（不是 CSS 模糊）。关闭：同会话内恢复原文。
 * 刷新重置：resetPrivacyOnBoot 清残留标记（模块加载早于组件渲染，
 * 抽屉开关态与 DOM 保持一致）。MobileNavigationDrawer 开关联动。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  PRIVACY_CLASS,
  disablePrivacyMask,
  enablePrivacyMask,
  isPrivacyEnabled,
  resetPrivacyOnBoot,
  setPrivacyMask,
} from '../lib/privacy-mask'
import MobileNavigationDrawer from '../components/MobileNavigationDrawer'
import { useReaderUi } from '../store/reader-ui'

let seeded: HTMLDivElement | null = null

function seedPrivacyDom(): void {
  seeded = document.createElement('div')
  seeded.innerHTML = [
    '<span data-privacy-text="" id="p-title">我的私密文章标题</span>',
    '<button data-privacy-text="" aria-label="订阅源：内部工具" id="p-btn">源按钮</button>',
    '<span id="p-open">这段不遮</span>',
  ].join('')
  document.body.appendChild(seeded)
}

afterEach(() => {
  disablePrivacyMask()
  localStorage.removeItem('lumirss-privacy-demo')
  // 只移除测试播种的容器（RTL cleanup 自己卸载 React 树，不能整体清 body）
  seeded?.remove()
  seeded = null
  vi.unstubAllGlobals()
})

describe('F113 隐私遮罩', () => {
  it('F113: 开启后 data-privacy-text 替换为 ▮ 且 aria-label 清空；负向：DOM 无原词；非目标元素不受影响', () => {
    seedPrivacyDom()
    setPrivacyMask(true)

    expect(document.documentElement.classList.contains(PRIVACY_CLASS)).toBe(true)
    expect(isPrivacyEnabled()).toBe(true)
    const title = document.getElementById('p-title') as HTMLElement
    const btn = document.getElementById('p-btn') as HTMLElement
    expect(title.textContent).not.toContain('我的私密文章标题')
    expect(title.textContent?.trim()).toMatch(/^▮+$/)
    expect(btn.hasAttribute('aria-label')).toBe(false) // aria-label 清空
    // 负向：整页 DOM 不残留原文（数据驱动替换，不是 CSS 模糊）
    expect(document.body.textContent).not.toContain('我的私密文章标题')
    expect(document.body.innerHTML).not.toContain('订阅源：内部工具')
    // 非 data-privacy-text 元素不受影响
    expect(document.getElementById('p-open')?.textContent).toBe('这段不遮')
  })

  it('F113: 关闭恢复原文；后续新增的 data-privacy-text 节点也被遮蔽', async () => {
    seedPrivacyDom()
    const cleanup = enablePrivacyMask()
    try {
      const title = document.getElementById('p-title') as HTMLElement
      expect(title.textContent).toMatch(/^▮+$/)
      disablePrivacyMask()
      expect(title.textContent).toBe('我的私密文章标题')

      // MutationObserver：开启后新增节点同样遮蔽。await 在 try 内完成——
      // （旧写法 sync return waitFor + 外层 finally 同步 disable 会在轮询
      // 开始前断开观察器，轮询永不收敛。）
      enablePrivacyMask()
      const added = document.createElement('span')
      added.setAttribute('data-privacy-text', '')
      added.textContent = '后加的秘密'
      document.body.appendChild(added)
      await waitFor(() => {
        expect(added.textContent).toMatch(/^▮+$/)
        expect(document.body.textContent).not.toContain('后加的秘密')
      })
    } finally {
      cleanup()
      disablePrivacyMask()
    }
  })

  it('F113: 刷新重置——残留标记被清（抽屉初始态与 DOM 一致）', () => {
    localStorage.setItem('lumirss-privacy-demo', '1')
    expect(isPrivacyEnabled()).toBe(true)
    resetPrivacyOnBoot()
    expect(isPrivacyEnabled()).toBe(false)
  })

  it('F113: 抽屉开关联动——点击开启 → 文本遮蔽；再点退出 → 恢复', async () => {
    useReaderUi.getState().openMobileSidebar()
    seedPrivacyDom()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MobileNavigationDrawer />
      </QueryClientProvider>,
    )
    const toggle = await screen.findByTestId('drawer-privacy-demo')
    fireEvent.click(toggle)
    await waitFor(() => {
      expect(document.getElementById('p-title')?.textContent).toMatch(/^▮+$/)
    })
    expect(document.body.textContent).not.toContain('我的私密文章标题')
    expect(toggle.getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(toggle)
    await waitFor(() => {
      expect(document.getElementById('p-title')?.textContent).toBe('我的私密文章标题')
    })
    expect(isPrivacyEnabled()).toBe(false)
  })
})
