/** F009 远程图片隐私加载 —— 管线单元（远程拦截/本地保留/例外恢复）
 * + 设置开关（device-local 持久）+ 刷新后默认态恢复。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  allowRemoteImage,
  blockRemoteImages,
  clearRemoteImageExceptions,
  decorateBlockedRemoteImages,
  isRemoteHttpUrl,
  readBlockRemoteImages,
  writeBlockRemoteImages,
} from '../lib/remote-images'
import {
  DEFAULT_APP_SETTINGS,
  normalizeSettings,
  useAppSettings,
} from '../store/app-settings'
import { ChineseTypographySettings } from '../components/settings/reader/ReaderDeepControls'

const LOCAL_HTML =
  '<img src="/api/v1/library/assets/snap.png" alt="快照"><img src="data:image/png;base64,xx" alt="内联"><p>正文</p>'
const REMOTE_HTML =
  '<p>开头</p><img src="https://img.example.com/a.png" alt="远程" srcset="a.png 1x"><img src="https://cdn.example.net/b.jpg" alt="远程二">'

beforeEach(() => {
  localStorage.clear()
  clearRemoteImageExceptions()
})

describe('F009 管线单元：blockRemoteImages', () => {
  it('F009: 远程 src 被摘除并存入 data-lumi-blocked-src；本地/快照/data: 保留', () => {
    const mixed = LOCAL_HTML + REMOTE_HTML
    const result = blockRemoteImages(mixed)
    expect(result.blockedCount).toBe(2)
    const doc = new DOMParser().parseFromString(result.html, 'text/html')
    // 远程 img：无 src 属性，原地址在 data-lumi-blocked-src
    const blocked = doc.querySelectorAll('img[data-lumi-image="blocked"]')
    expect(blocked.length).toBe(2)
    expect(blocked[0]!.getAttribute('data-lumi-blocked-src')).toBe('https://img.example.com/a.png')
    expect(blocked[0]!.getAttribute('src')).toBeNull()
    expect(blocked[0]!.getAttribute('srcset')).toBeNull()
    // 本地快照与 data: 不受影响
    expect(doc.querySelector('img[src="/api/v1/library/assets/snap.png"]')).not.toBeNull()
    expect(doc.querySelector('img[src="data:image/png;base64,xx"]')).not.toBeNull()
  })

  it('F009: 会话例外中的 URL 不再拦截（点击恢复后重跑管线保持已加载）', () => {
    allowRemoteImage('https://img.example.com/a.png')
    const result = blockRemoteImages(REMOTE_HTML)
    expect(result.blockedCount).toBe(1)
    const doc = new DOMParser().parseFromString(result.html, 'text/html')
    expect(doc.querySelector('img[src="https://img.example.com/a.png"]')).not.toBeNull()
    expect(doc.querySelector('img[data-lumi-blocked-src="https://cdn.example.net/b.jpg"]')).not.toBeNull()
  })

  it('F009: isRemoteHttpUrl 保守判定（相对路径/协议相对均非远程）', () => {
    expect(isRemoteHttpUrl('https://a.example/x.png')).toBe(true)
    expect(isRemoteHttpUrl('http://a.example/x.png')).toBe(true)
    expect(isRemoteHttpUrl('/api/v1/library/assets/a.png')).toBe(false)
    expect(isRemoteHttpUrl('assets/a.png')).toBe(false)
    expect(isRemoteHttpUrl('data:image/png;base64,xx')).toBe(false)
  })

  it('F009: 占位经装饰变为「加载本图」按钮，点击恢复真实 img（受控 DOM 构造）', () => {
    const { html } = blockRemoteImages(REMOTE_HTML)
    const host = document.createElement('div')
    host.innerHTML = html
    decorateBlockedRemoteImages(host)
    const buttons = host.querySelectorAll('button.lumi-blocked-image')
    expect(buttons.length).toBe(2)
    expect(buttons[0]!.textContent).toBe('加载本图')
    // XSS 探针：占位数据属性内容不进入任何 innerHTML 拼接路径
    expect(host.innerHTML).not.toContain('<script')
    fireEvent((buttons[0] as HTMLButtonElement), new MouseEvent('click', { bubbles: true }))
    const restored = host.querySelector('img[src="https://img.example.com/a.png"]')
    expect(restored).not.toBeNull()
    // 会话例外已记录：再次拦截不生效
    expect(blockRemoteImages(REMOTE_HTML).blockedCount).toBe(1)
  })
})

describe('F009 设置开关（device-local）', () => {
  it('F009: 默认关闭；写入后读取保持；刷新（重读）后默认态由存储决定', () => {
    expect(readBlockRemoteImages()).toBe(false)
    expect(DEFAULT_APP_SETTINGS.readerBlockRemoteImages).toBe(false)
    writeBlockRemoteImages(true)
    expect(readBlockRemoteImages()).toBe(true)
    // 解析管线（持久化恢复路径）
    const parsed = normalizeSettings({ readerBlockRemoteImages: true })
    expect(parsed.readerBlockRemoteImages).toBe(true)
    writeBlockRemoteImages(false)
    expect(readBlockRemoteImages()).toBe(false)
  })

  it('F009: 设置开关切换 → store 更新 readerBlockRemoteImages', () => {
    useAppSettings.setState({
      settings: { ...DEFAULT_APP_SETTINGS, readerBlockRemoteImages: false },
    })
    render(<ChineseTypographySettings />)
    fireEvent.change(screen.getByRole('combobox', { name: '默认不加载远程图片' }), {
      target: { value: 'on' },
    })
    expect(useAppSettings.getState().settings.readerBlockRemoteImages).toBe(true)
  })
})
