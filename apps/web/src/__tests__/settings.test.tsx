/** SettingsModal 测试 — 0010 Gate A（AC3/AC4 + 外观页真实生效）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import SettingsModal from '../components/settings/SettingsModal'
import { useAppSettings, SETTINGS_STORAGE_KEY } from '../store/app-settings'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

function renderModal() {
  render(withQueryClient(<SettingsModal open onClose={vi.fn()} />))
}

describe('SettingsModal — AC3（结构）', () => {
  it('左导航渲染 13 个分类（备份与恢复已并入数据控制）', () => {
    renderModal()
    const nav = screen.getByRole('navigation', { name: '设置分类' })
    const items = nav.querySelectorAll('button')
    expect(items).toHaveLength(13)
    expect(screen.getByRole('button', { name: /通用/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /外观/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^阅读$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^翻译$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /文章过滤/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /RSSHub/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /数据控制/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /备份与恢复/ })).toBeNull()
    expect(screen.getByRole('button', { name: /关于/ })).toBeInTheDocument()
  })

  it('导航切换 → 内容区标题与设置行切换（aria-current）', async () => {
    renderModal()
    fireEvent.click(screen.getByRole('button', { name: /外观/ }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 2, name: '外观' })).toBeInTheDocument()
      expect(screen.getByText('主题模式')).toBeInTheDocument()
    })
    // 0017：Reader 排版已移出外观 → 阅读分类
    expect(screen.queryByText('正文字号')).not.toBeInTheDocument()
    // 默认分类（通用）不再高亮
    expect(screen.getByRole('button', { name: /通用/ })).not.toHaveAttribute('aria-current')
    // 阅读分类承载排版 Slider
    fireEvent.click(screen.getByRole('button', { name: /^阅读$/ }))
    await waitFor(() => {
      expect(screen.getByRole('slider', { name: '字号' })).toBeInTheDocument()
    })
  })
})

describe('SettingsModal — AC4（关闭路径）', () => {
  it('Escape 关闭（Dialog primitive 提供）', () => {
    const onClose = vi.fn()
    render(withQueryClient(<SettingsModal open onClose={onClose} />))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('role=dialog + aria-modal（模态语义）', () => {
    renderModal()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })
})

describe('SettingsModal — 外观页真实生效（Gate A 迁移验收）', () => {
  it('主题模式切换 → store + localStorage + data-theme 同步', async () => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    renderModal()
    fireEvent.click(screen.getByRole('button', { name: /外观/ }))
    await waitFor(() => screen.getByRole('combobox', { name: '主题模式' }))

    fireEvent.change(screen.getByRole('combobox', { name: '主题模式' }), {
      target: { value: 'dark' },
    })
    await waitFor(() => {
      expect(useAppSettings.getState().settings.themeMode).toBe('dark')
      expect(
        JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).themeMode,
      ).toBe('dark')
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    })
    useAppSettings.getState().reset()
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('Reader 连续字号 Slider → CSS 变量挂载（Gate B 接线点）', async () => {
    localStorage.clear()
    renderModal()
    fireEvent.click(screen.getByRole('button', { name: /^阅读$/ }))
    const slider = await screen.findByRole('slider', { name: '字号' })

    fireEvent.change(slider, { target: { value: '21' } })
    await waitFor(() => {
      expect(document.documentElement.style.getPropertyValue('--lumi-reader-font-size')).toBe(
        '21px',
      )
    })
    useAppSettings.getState().reset()
    localStorage.clear()
  })
})

describe('SettingsModal — 通用页清洁原则', () => {
  it('不向用户暴露未实现选项：无 English/planned/i18n、无侧栏隐藏已读、无未读圆点开关', () => {
    renderModal()
    // 界面语言是静态展示（只有简体中文），不是不可用的下拉
    expect(screen.queryByRole('combobox', { name: '界面语言' })).toBeNull()
    expect(screen.getByText('简体中文', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByText(/planned/)).toBeNull()
    expect(screen.queryByText(/English 将随/)).toBeNull()
    // 未实现的侧栏隐藏已读与误导性未读圆点开关已整体移除
    expect(screen.queryByText('侧栏隐藏已读')).toBeNull()
    expect(screen.queryByText('显示未读圆点')).toBeNull()
    // 真实可用的开关保留
    expect(screen.getByRole('switch', { name: '已读条目变暗开关' })).toBeEnabled()
    expect(screen.getByRole('switch', { name: '按日期分组开关' })).toBeEnabled()
    expect(screen.getByRole('switch', { name: '启动时仅看未读开关' })).toBeEnabled()
  })
})
