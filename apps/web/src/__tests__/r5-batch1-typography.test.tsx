/** R5 批1 测试 — F068 字重 / F069 图片最大宽度 / F070 首图破格 /
 * F071 figure caption 控制 / F064 纸张质感纹理。
 *
 * 覆盖：设备本设置的归一化（非法回退默认）、CSS 变量与 data 标记挂载、
 * article pipeline 首图标记（DOMPurify 边界不变式）、Aa 面板快捷控件
 * 与同一 settings store 的直连。 */

import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ReaderAaPanel from '../components/ReaderAaPanel'
import {
  DEFAULT_APP_SETTINGS,
  SETTINGS_STORAGE_KEY,
  applyReaderTypography,
  normalizeSettings,
  readerTypographyVars,
  useAppSettings,
} from '../store/app-settings'
import { renderArticleHtml } from '../lib/article-pipeline'
import { clearArticleHtmlCaches } from '../lib/article-pipeline'

function withQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  clearArticleHtmlCaches()
})

describe('F068/F069/F071/F064/F070 — 设备本设置归一化', () => {
  it('默认值：字重 400 / 图片 100% / caption 显示 / 纹理与破格关', () => {
    const s = normalizeSettings({})
    expect(s.readerFontWeight).toBe(400)
    expect(s.readerImageMaxWidth).toBe('100%')
    expect(s.readerCaptionMode).toBe('show')
    expect(s.readerFirstImageFullBleed).toBe(false)
    expect(s.readerPaperTexture).toBe(false)
  })

  it('合法值原样保留（round-trip）', () => {
    const s = normalizeSettings({
      readerFontWeight: 600,
      readerImageMaxWidth: '75%',
      readerCaptionMode: 'hover',
      readerFirstImageFullBleed: true,
      readerPaperTexture: true,
    })
    expect(s.readerFontWeight).toBe(600)
    expect(s.readerImageMaxWidth).toBe('75%')
    expect(s.readerCaptionMode).toBe('hover')
    expect(s.readerFirstImageFullBleed).toBe(true)
    expect(s.readerPaperTexture).toBe(true)
  })

  it('非法值回退默认（不抛错、不落半态）', () => {
    const s = normalizeSettings({
      readerFontWeight: 350,
      readerImageMaxWidth: '50%',
      readerCaptionMode: 'always',
      readerFirstImageFullBleed: 'yes',
      readerPaperTexture: 1,
    })
    expect(s.readerFontWeight).toBe(DEFAULT_APP_SETTINGS.readerFontWeight)
    expect(s.readerImageMaxWidth).toBe(DEFAULT_APP_SETTINGS.readerImageMaxWidth)
    expect(s.readerCaptionMode).toBe(DEFAULT_APP_SETTINGS.readerCaptionMode)
    expect(s.readerFirstImageFullBleed).toBe(false)
    expect(s.readerPaperTexture).toBe(false)
  })
})

describe('F068/F069 — CSS 变量与 data 标记挂载', () => {
  it('readerTypographyVars 输出字重与图片宽度变量', () => {
    const vars = readerTypographyVars({
      ...DEFAULT_APP_SETTINGS,
      readerFontWeight: 500,
      readerImageMaxWidth: '60%',
    })
    expect(vars['--lumi-reader-font-weight']).toBe('500')
    expect(vars['--lumi-reader-image-max-width']).toBe('60%')
  })

  it('applyReaderTypography 挂 data 标记（caption 模式 / 纹理 / 背景档）', () => {
    applyReaderTypography({
      ...DEFAULT_APP_SETTINGS,
      readerBackground: 'paper',
      readerPaperTexture: true,
      readerCaptionMode: 'hidden',
      readerImageMaxWidth: '75%',
      readerFirstImageFullBleed: true,
    })
    const root = document.documentElement
    expect(root.dataset.readerBgPreset).toBe('paper')
    expect(root.dataset.readerPaperTexture).toBe('true')
    expect(root.dataset.readerCaptionMode).toBe('hidden')
    expect(root.dataset.readerImageMaxWidth).toBe('75%')
    expect(root.dataset.readerFirstImageFullBleed).toBe('true')
  })
})

describe('F070 — article pipeline 首图破格标记', () => {
  const RAW = '<p>引言</p><img src="https://cdn.example/a.png" alt="首图"><p>正文</p>'

  it('开启：第一张 img 获得 data-lumi-first-image', async () => {
    const out = await renderArticleHtml(RAW, {
      conversion: 'off',
      bionic: false,
      codeTheme: null,
      firstImageFullBleed: true,
    })
    expect(out).toContain('data-lumi-first-image')
  })

  it('关闭（默认）：不产生标记', async () => {
    const out = await renderArticleHtml(RAW, {
      conversion: 'off',
      bionic: false,
      codeTheme: null,
    })
    expect(out).not.toContain('data-lumi-first-image')
  })

  it('标记 transform 不破坏 DOMPurify 边界（恶意属性仍被清洗）', async () => {
    const out = await renderArticleHtml(
      '<img src=x onerror="alert(1)"><p>bad</p>',
      {
        conversion: 'off',
        bionic: false,
        codeTheme: null,
        firstImageFullBleed: true,
      },
    )
    expect(out).not.toMatch(/onerror/i)
    expect(out).toContain('data-lumi-first-image')
  })
})

describe('ReaderAaPanel — 批1 排版快捷控件（同一 settings store）', () => {
  it('F068：字重档位直连 store 并持久化', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('正文字重'), { target: { value: '600' } })
    expect(useAppSettings.getState().settings.readerFontWeight).toBe(600)
    expect(JSON.parse(localStorage.getItem(SETTINGS_STORAGE_KEY)!).readerFontWeight).toBe(600)
  })

  it('F069：图片最大宽度档位直连 store', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('图片最大宽度'), { target: { value: '60%' } })
    expect(useAppSettings.getState().settings.readerImageMaxWidth).toBe('60%')
  })

  it('F071：图片说明显示模式直连 store', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.change(screen.getByLabelText('图片说明显示'), { target: { value: 'hover' } })
    expect(useAppSettings.getState().settings.readerCaptionMode).toBe('hover')
  })

  it('F070/F064：首图破格与纸张纹理开关', () => {
    render(withQueryClient(<ReaderAaPanel />))
    fireEvent.click(screen.getByRole('button', { name: '阅读样式' }))
    fireEvent.click(screen.getByRole('switch', { name: '首图破格满宽' }))
    fireEvent.click(screen.getByRole('switch', { name: '纸张质感纹理' }))
    const s = useAppSettings.getState().settings
    expect(s.readerFirstImageFullBleed).toBe(true)
    expect(s.readerPaperTexture).toBe(true)
  })
})
