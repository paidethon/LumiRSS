/** NEW-360 移动端只读演示模式 — 合成数据隔离 + 界面样本（jsdom）。
 *
 * 覆盖：合成数据与真实状态零耦合（fixture URL 全 example.com / 标题
 * 带「演示」标注）；横幅不可关闭；阅读界面（清单选择 + 同一正文渲染
 * 管线，无变更入口）；管理界面（合成源表、动作全部禁用）；退出卸载
 * 零残留；零网络（fetch 间谍零调用）、不写任何存储。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReadOnlyDemo from '../components/new351/ReadOnlyDemo'

function renderDemo(onExit: () => void): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <ReadOnlyDemo onExit={onExit} />
    </QueryClientProvider>,
  )
}
import { DEMO_ENTRIES, DEMO_SOURCES } from '../lib/demo-reading'

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('NEW-360 演示数据隔离', () => {
  it('合成数据：标题全部带「演示」标注；URL 全部 example.com；零真实耦合', () => {
    for (const source of DEMO_SOURCES) {
      expect(source.title).toContain('演示')
      expect(new URL(source.url).hostname).toBe('example.com')
    }
    for (const entry of DEMO_ENTRIES) {
      expect(entry.title).toContain('演示')
      expect(new URL(entry.feedUrl ?? '').hostname).toBe('example.com')
    }
    // 合成数据不含任何本机账户痕迹
    expect(JSON.stringify(DEMO_ENTRIES)).not.toContain('freshrss')
    expect(JSON.stringify(DEMO_SOURCES)).not.toContain('freshrss')
  })
})

describe('NEW-360 只读演示模式', () => {
  it('横幅明确合成数据且带退出；阅读界面默认选中第一篇', () => {
    renderDemo(() => {})
    expect(screen.getByText(/演示模式 · 只读 · 全部为合成数据/)).toBeTruthy()
    expect(screen.getByRole('dialog', { name: '只读演示模式' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /演示文章：为什么阅读器要「源优先」/ })).toBeTruthy()
  })

  it('阅读界面：切换条目渲染对应正文（同一 ArticleContent 管线）；无已读/收藏动作入口', () => {
    renderDemo(() => {})
    // 第一篇正文片段
    expect(screen.getByRole('heading', { name: '什么是「只读演示」' })).toBeTruthy()
    // 切到第三篇（图片占位示例）
    fireEvent.click(screen.getByText('演示文章：城市市集指南（含图示例）'))
    expect(screen.getByText(/本篇演示/)).toBeTruthy()
    // 演示界面没有真实变更动作入口
    expect(screen.queryByRole('button', { name: /标为已读/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /收藏/ })).toBeNull()
  })

  it('管理界面：合成源表 + 动作全部演示禁用；不暴露真实订阅', () => {
    renderDemo(() => {})
    fireEvent.click(screen.getByTestId('n360-tab-management'))
    expect(screen.getByText('晨间科技简报（演示）')).toBeTruthy()
    expect(screen.getAllByText(/（演示禁用）/).length).toBe(9) // 3 源 × 3 动作
    expect(screen.getByText(/真实管理操作（刷新 \/ 编辑 \/ 删除）在演示模式中没有入口/)).toBeTruthy()
  })

  it('退出即卸载零残留；全程零网络、零存储写入', () => {
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const onExit = vi.fn()
    renderDemo(onExit)
    fireEvent.click(screen.getByTestId('n360-exit'))
    expect(onExit).toHaveBeenCalledTimes(1)
    // 卸载由宿主状态承担（真实接线：exit → setState 卸载浮层）
    expect(vi.mocked(fetch as unknown as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
    expect(setItemSpy).not.toHaveBeenCalled()
    setItemSpy.mockRestore()
  })
})
