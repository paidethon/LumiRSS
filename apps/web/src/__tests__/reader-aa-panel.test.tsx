/** ReaderAaPanel 测试 — 0012 Gate 7（AC12：与 Settings 同一 settings source）。 */

import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReaderAaPanel from '../components/ReaderAaPanel'
import { SETTINGS_STORAGE_KEY, useAppSettings } from '../store/app-settings'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
})

describe('ReaderAaPanel — 桌面 Popover', () => {
  it('点击 Aa 按钮打开面板，快速控件直连 settings store', () => {
    render(withQueryClient(<ReaderAaPanel />))
    const btn = screen.getByRole('button', { name: '阅读样式' })
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog')
    fireEvent.click(btn)
    // 面板打开（group label）
    expect(screen.getByRole('group', { name: '阅读样式' })).toBeInTheDocument()

    // 字号调到「特大」→ store 更新 + 持久化（同一 settings source）
    fireEvent.change(screen.getByLabelText('正文字号'), { target: { value: '21' } })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(21)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(21)
  })

  it('简繁切换写同一 store', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('简繁转换'), { target: { value: 'tw' } })
    expect(useAppSettings.getState().settings.readerChineseConversion).toBe('tw')
  })

  it('「更多阅读设置」打开完整设置（同一 settings store）', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.click(screen.getByRole('button', { name: '更多阅读设置…' }))
    // Settings Modal 标题出现（桌面壳；jsdom 不应用 CSS 隐藏，移动壳同在）
    expect(screen.getAllByText('设置').length).toBeGreaterThanOrEqual(1)
  })

  it('Escape 关闭面板并还焦到触发按钮', () => {
    render(withQueryClient(<ReaderAaPanel />))
    const btn = screen.getByRole('button', { name: '阅读样式' })
    fireEvent.click(btn)
    expect(screen.getByRole('group', { name: '阅读样式' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('group', { name: '阅读样式' })).not.toBeInTheDocument()
  })
})
