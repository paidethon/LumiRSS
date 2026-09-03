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
  it('左导航渲染 14 个分类（0010a Gate E：9 → 13；0017：13 → 14）', () => {
    renderModal()
    const nav = screen.getByRole('navigation', { name: '设置分类' })
    const items = nav.querySelectorAll('button')
    expect(items).toHaveLength(14)
    expect(screen.getByRole('button', { name: /通用/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /外观/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^阅读$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^翻译$/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /文章过滤/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /RSSHub/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /备份与恢复/ })).toBeInTheDocument()
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

describe('SettingsModal — planned 诚实原则', () => {
  it('planned 行（界面语言）控件禁用 + planned 徽标', async () => {
    renderModal()
    // 通用页默认选中，界面语言行存在
    const select = screen.getByRole('combobox', { name: '界面语言' })
    expect(select).toBeDisabled()
    expect(screen.getByText('planned · i18n')).toBeInTheDocument()
  })

  it('「侧栏隐藏已读」planned（需要未读数契约，无已批准里程碑编号——0014a 清理 stale 0013）', () => {
    renderModal()
    const toggle = screen.getByRole('switch', { name: '侧栏隐藏已读开关' })
    expect(toggle).toBeDisabled()
    expect(screen.getByText('planned', { exact: true })).toBeInTheDocument()
    expect(screen.queryByText(/planned · 0013/)).toBeNull()
  })
})
