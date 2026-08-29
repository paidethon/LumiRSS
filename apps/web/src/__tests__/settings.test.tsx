/** SettingsDialog 测试 — 0009 Gate 4（AC18/AC19）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SettingsDialog from '../components/SettingsDialog'
import { useTheme } from '../store/theme'
import { THEME_STORAGE_KEY } from '../lib/theme'

function renderDialog() {
  render(<SettingsDialog open onClose={vi.fn()} />)
}

describe('SettingsDialog — AC18（Appearance 真实可用）', () => {
  it('主题模式切换真实生效（localStorage + data-theme）', async () => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    renderDialog()
    const select = screen.getByRole('combobox', { name: '主题模式' })
    fireEvent.change(select, { target: { value: 'dark' } })
    await waitFor(() => {
      expect(useTheme.getState().mode).toBe('dark')
      expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    })
    // 恢复
    useTheme.getState().setMode('system')
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('Reader 背景切换写 localStorage + 挂 data-reader', () => {
    localStorage.clear()
    // 构造 Reader 容器（真实应用中由 Reader.tsx 渲染）
    const readerEl = document.createElement('div')
    readerEl.className = 'bg-[var(--lumi-reader-bg)]'
    document.body.appendChild(readerEl)

    renderDialog()
    fireEvent.change(screen.getByRole('combobox', { name: '阅读背景' }), {
      target: { value: 'sepia' },
    })
    expect(localStorage.getItem('lumirss-reader-bg')).toBe('sepia')
    expect(readerEl.getAttribute('data-reader')).toBe('sepia')

    // follow = 移除属性 + 清 storage
    fireEvent.change(screen.getByRole('combobox', { name: '阅读背景' }), {
      target: { value: 'follow' },
    })
    expect(localStorage.getItem('lumirss-reader-bg')).toBeNull()
    expect(readerEl.hasAttribute('data-reader')).toBe(false)
    readerEl.remove()
    localStorage.clear()
  })
})

describe('SettingsDialog — AC19（planned 无假控件）', () => {
  it('占位分组带 planned 徽标', () => {
    renderDialog()
    const badges = screen.getAllByText('planned')
    // 阅读 / 订阅与来源 / AI / 数据与备份
    expect(badges.length).toBe(4)
  })

  it('planned 分组内没有任何可交互控件（无假保存）', () => {
    const { container } = render(<SettingsDialog open onClose={vi.fn()} />)
    // 全部 combobox 只属于 Appearance（2 个：主题模式 + 阅读背景）
    expect(container.querySelectorAll('select')).toHaveLength(2)
    // planned 分组无 button/switch/input
    const planned = screen.getAllByText('planned').map((b) => b.closest('section'))
    for (const sec of planned) {
      expect(sec?.querySelector('button, input, [role="switch"]')).toBeNull()
    }
  })

  it('role=dialog + Escape 关闭语义（Dialog primitive 提供）', () => {
    const onClose = vi.fn()
    render(<SettingsDialog open onClose={onClose} />)
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
