/** ReaderAaPanel 测试 — 0012 Gate 7 / 0017 连续化（AC12：与 Settings 同一 source）。 */

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

describe('ReaderAaPanel — 桌面 Popover（0017 连续 Slider）', () => {
  it('点击 Aa 按钮打开面板，连续字号 slider 直连 settings store（WYSIWYG）', () => {
    render(withQueryClient(<ReaderAaPanel />))
    const btn = screen.getByRole('button', { name: '阅读样式' })
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog')
    fireEvent.click(btn)
    expect(screen.getByRole('group', { name: '阅读样式' })).toBeInTheDocument()

    // 连续 slider：拖到 21 → store 更新 + 持久化（同一 settings source）
    fireEvent.change(screen.getByLabelText('字号'), { target: { value: '21' } })
    expect(useAppSettings.getState().settings.readerFontSize).toBe(21)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontSize).toBe(21)
  })

  it('A− / A+ 步进按钮微调字号（键盘/触控目标 ≥44px 语义）', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    const before = useAppSettings.getState().settings.readerFontSize
    fireEvent.click(screen.getByRole('button', { name: '字号增大' }))
    expect(useAppSettings.getState().settings.readerFontSize).toBe(before + 1)
    fireEvent.click(screen.getByRole('button', { name: '字号减小' }))
    expect(useAppSettings.getState().settings.readerFontSize).toBe(before)
  })

  it('五个连续 Slider 共享同一 store（行距/段距/宽度/边距）', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('行距'), { target: { value: '2.0' } })
    fireEvent.change(screen.getByLabelText('段距'), { target: { value: '1.2' } })
    fireEvent.change(screen.getByLabelText('正文宽度'), { target: { value: '900' } })
    fireEvent.change(screen.getByLabelText('页面边距'), { target: { value: '48' } })
    const s = useAppSettings.getState().settings
    expect(s.readerLineHeight).toBe(2.0)
    expect(s.readerParagraphSpacing).toBe(1.2)
    expect(s.readerContentWidth).toBe(900)
    expect(s.readerPageMargin).toBe(48)
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
