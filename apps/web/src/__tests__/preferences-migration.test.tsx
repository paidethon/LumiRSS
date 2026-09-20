/** F32 偏好迁移 UI — 导出载荷形状 / 导入 diff 预览 / 应用。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PreferencesMigrationSection } from '../components/settings/PreferencesMigrationSection'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function setup() {
  const current = {
    ...DEFAULT_APP_SETTINGS,
    readerFontSize: 19,
    readerImageMode: 'hidden' as const,
  }
  useAppSettings.setState({ settings: current })
  render(<PreferencesMigrationSection />)
}

describe('PreferencesMigrationSection（F32）', () => {
  it('导出：生成版本化 JSON 下载（只含偏好）', async () => {
    const blobs: Blob[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation(((blob: Blob) => {
      blobs.push(blob)
      return 'blob:mock'
    }) as typeof URL.createObjectURL)
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
      this: HTMLAnchorElement,
    ) {
      // 下载动作被拦截即可
    })
    setup()
    fireEvent.click(screen.getByRole('button', { name: '导出偏好' }))
    await waitFor(() => expect(blobs.length).toBeGreaterThan(0))
    const payload = JSON.parse(await blobs[0].text())
    expect(payload.kind).toBe('lumirss-preferences')
    expect(payload.schemaVersion).toBe(1)
    expect(payload.values.readerFontSize).toBe(19)
    // 不含任何密钥类键
    expect(await blobs[0].text()).not.toMatch(/password|secret|token|api[_-]?key/i)
  })

  it('导入：diff 预览后应用生效', async () => {
    setup()
    const incoming = {
      schemaVersion: 1,
      kind: 'lumirss-preferences',
      values: { readerFontSize: 14, readerJustify: true },
    }
    const file = new File([JSON.stringify(incoming)], 'prefs.json', { type: 'application/json' })
    const input = screen.getByLabelText('选择偏好文件')
    Object.defineProperty(input, 'files', { value: [file] })
    fireEvent.change(input)

    // diff 预览：当前 19 → 导入 14（文本跨节点，按 textContent 匹配）
    await screen.findByText(/将修改 2 项偏好/)
    const row = await screen.findByText((_content, element) =>
      element?.textContent === 'readerFontSize: 19 → 14' && element.tagName === 'LI',
    )
    expect(row).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /仅应用所选/ }))
    await waitFor(() => {
      expect(useAppSettings.getState().settings.readerFontSize).toBe(14)
      expect(useAppSettings.getState().settings.readerJustify).toBe(true)
    })
  })

  it('导入非法文件给出诚实错误', async () => {
    setup()
    const file = new File([JSON.stringify({ kind: 'other', schemaVersion: 9 })], 'x.json', {
      type: 'application/json',
    })
    const input = screen.getByLabelText('选择偏好文件')
    Object.defineProperty(input, 'files', { value: [file] })
    fireEvent.change(input)
    await screen.findByText(/不是有效的 LumiRSS 偏好文件/)
  })
})
