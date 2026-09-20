/** F112 —— 自定义 CSS 隔离与护栏（Web 层）。
 *
 * checkCssSafety：@import / 绝对 url() 拦截（白名单 = 相对路径 / # 片段）；
 * validateCustomCss：解析失败诚实拒绝。
 * CustomCssEditor：预览沙盒（示例文章 + 前缀化样式仅命中沙盒）、
 * 保存拦截非法输入、恢复上一有效版本（备份键）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { CustomCssEditor } from '../components/settings/AppearanceControls'
import {
  backupCurrentCustomCss,
  checkCssSafety,
  loadBackupCustomCss,
  validateCustomCss,
} from '../lib/custom-css'
import { prefixCustomCss } from '../lib/reader-style'
import { useAppSettings } from '../store/app-settings'
import { DEFAULT_APP_SETTINGS } from '../store/app-settings'

describe('F112 CSS 拦截与校验（lib）', () => {
  it('F112: @import / 绝对 url 拒绝；相对路径与 # 片段放行；解析失败拒绝', () => {
    expect(checkCssSafety('@import url("evil.css");').ok).toBe(false)
    expect(checkCssSafety('a { background: url(http://evil.com/x.png); }').ok).toBe(false)
    expect(checkCssSafety('a { background: url(https://evil.com/x.png); }').ok).toBe(false)
    expect(checkCssSafety('a { mask: url(//evil.com/x.svg); }').ok).toBe(false)
    expect(checkCssSafety('a { background: url("/abs/path.png"); }').ok).toBe(false)
    // 白名单内
    expect(checkCssSafety('a { background: url(img/pic.png); }').ok).toBe(true)
    expect(checkCssSafety('a { clip-path: url(#shape); }').ok).toBe(true)
    // 解析失败（花括号不配对）
    expect(validateCustomCss('p { color: red;')).not.toBeNull()
    expect(prefixCustomCss('p { color: red;')).toBeNull()
    // 合法：选择器自动加 .lumi-reader 前缀
    expect(prefixCustomCss('p { color: red; }')).toBe('.lumi-reader p{ color: red; }')
  })

  it('F112: 上一有效版本备份——保存前备份旧值，恢复取回；一致时返回 null', () => {
    localStorage.removeItem('lumirss-custom-css-last-valid')
    backupCurrentCustomCss('p { color: blue; }')
    expect(loadBackupCustomCss('p { color: red; }')).toBe('p { color: blue; }')
    expect(loadBackupCustomCss('p { color: blue; }')).toBeNull() // 与当前一致 → null
    localStorage.removeItem('lumirss-custom-css-last-valid')
    expect(loadBackupCustomCss('anything')).toBeNull()
  })
})

describe('F112 CustomCssEditor（沙盒 / 拦截 / 恢复）', () => {
  const key = (v: Record<string, unknown>): void => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, ...v } as typeof DEFAULT_APP_SETTINGS,
    })
  }

  afterEach(() => {
    localStorage.clear()
    useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
    vi.restoreAllMocks()
  })

  it('F112: 预览沙盒渲染示例文章；非法草稿显示「预览不可用」；@import 被拦截', async () => {
    key({ customCss: 'p { color: rgb(1, 2, 3); }' })
    render(<CustomCssEditor />)
    fireEvent.click(screen.getByRole('button', { name: '预览' }))
    const sandbox = document.querySelector('[data-css-preview-sandbox]')
    expect(sandbox?.textContent).toContain('示例文章')
    // 前缀化样式注入（沙盒内命中 .lumi-reader）
    expect(sandbox?.querySelector('style')?.textContent).toContain('.lumi-reader p')

    // 非法草稿 → 沙盒诚实提示
    fireEvent.change(screen.getByLabelText('自定义 CSS'), { target: { value: 'p { color: red;' } })
    await waitFor(() => expect(sandbox?.textContent).toContain('预览不可用'))

    // @import → 保存被拦截（app-settings 不变）
    const before = useAppSettings.getState().settings.customCss
    fireEvent.change(screen.getByLabelText('自定义 CSS'), {
      target: { value: '@import url("http://evil.com/x.css");' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(screen.getByRole('alert').textContent).toContain('@import')
    expect(useAppSettings.getState().settings.customCss).toBe(before)
  })

  it('F112: 保存成功 → 上一有效版本可一键恢复', () => {
    localStorage.clear()
    render(<CustomCssEditor />)
    fireEvent.change(screen.getByLabelText('自定义 CSS'), {
      target: { value: 'p { line-height: 2; }' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    // 成功后：当前生效为草稿，备份 = 旧值（''）；恢复按钮出现
    expect(useAppSettings.getState().settings.customCss).toBe('p { line-height: 2; }')
    const restore = screen.getByRole('button', { name: '恢复上一有效版本' })
    fireEvent.click(restore)
    expect(useAppSettings.getState().settings.customCss).toBe('')
    expect((screen.getByLabelText('自定义 CSS') as HTMLTextAreaElement).value).toBe('')
  })
})
