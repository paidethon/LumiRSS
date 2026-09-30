/** NEW-358 链接操作面板 — 纯逻辑 + Sheet + 长按手势（jsdom）。
 *
 * 覆盖：外链判定 / 域名解析；稍后打开清单（有界 / 去重 / 移除）；剪藏
 * 一次性预填交接；Sheet 主路径（域名显示、复制、稍后打开切换、清单
 * 打开/移除）；长按手势（550ms 弹出 + 吞掉后续 click；轻点不弹）。
 * 零网络：fetch 间谍零调用。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRef } from 'react'
import LinkActionSheet, { LinkActionGesture, LINK_LONG_PRESS_MS } from '../components/new351/LinkActionSheet'
import {
  CLIP_PREFILL_SESSION_KEY,
  LINK_LATER_LIMIT,
  LINK_LATER_STORAGE_KEY,
  addLinkLater,
  clearLinkLater,
  isExternalHttpUrl,
  linkDomain,
  readLinkLater,
  removeLinkLater,
  stageClipPrefill,
} from '../lib/link-actions'
import { useReaderUi } from '../store/reader-ui'

const BASE = 'https://reader.example/article/1'

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  useReaderUi.setState({ section: 'home' })
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('NEW-358 链接操作纯逻辑', () => {
  it('外链判定：跨源 http(s) true；同源 / 锚点 / javascript: false', () => {
    expect(isExternalHttpUrl('https://other.example/x', BASE)).toBe(true)
    expect(isExternalHttpUrl('/relative/x', BASE)).toBe(false)
    expect(isExternalHttpUrl(`${BASE}#sec`, BASE)).toBe(false)
    expect(isExternalHttpUrl('javascript:alert(1)', BASE)).toBe(false)
    expect(isExternalHttpUrl('mailto:a@b.c', BASE)).toBe(false)
  })

  it('域名解析：有效 → hostname；无效 → null', () => {
    expect(linkDomain('https://cdn.example.com/a/b?x=1')).toBe('cdn.example.com')
    expect(linkDomain('not a url')).toBeNull()
  })

  it('稍后打开清单：加入 / 幂等去重 / 移除 / 有界逐出最旧', () => {
    addLinkLater('https://a.example/1')
    addLinkLater('https://a.example/1')
    addLinkLater('https://b.example/2')
    let items = readLinkLater()
    expect(items.map((i) => i.url)).toEqual(['https://b.example/2', 'https://a.example/1'])
    expect(items[1]!.domain).toBe('a.example')
    removeLinkLater('https://a.example/1')
    expect(readLinkLater().map((i) => i.url)).toEqual(['https://b.example/2'])
    for (let i = 0; i < LINK_LATER_LIMIT + 5; i += 1) addLinkLater(`https://c.example/${i}`)
    items = readLinkLater()
    expect(items.length).toBe(LINK_LATER_LIMIT)
    expect(items.some((i) => i.url === 'https://b.example/2')).toBe(false)
    clearLinkLater()
    expect(readLinkLater()).toEqual([])
  })

  it('剪藏交接：写一次性预填键（sessionStorage），零网络', () => {
    expect(stageClipPrefill('https://a.example/clip-me')).toBe(true)
    expect(window.sessionStorage.getItem(CLIP_PREFILL_SESSION_KEY)).toBe('https://a.example/clip-me')
  })

  it('损坏清单 JSON → 空清单（诚实回退）', () => {
    window.localStorage.setItem(LINK_LATER_STORAGE_KEY, '{broken')
    expect(readLinkLater()).toEqual([])
  })
})

describe('NEW-358 链接操作 Sheet', () => {
  it('显示域名与地址；复制链接写剪贴板并反馈', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    render(<LinkActionSheet url="https://docs.example.com/guide?utm_source=x" onClose={() => {}} />)
    expect(screen.getByText('docs.example.com')).toBeTruthy()
    fireEvent.click(screen.getByTestId('n358-copy'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://docs.example.com/guide?utm_source=x'))
    expect(await screen.findByText('已复制')).toBeTruthy()
    // 净链接：预览行显示将移除的跟踪参数
    fireEvent.click(screen.getByTestId('n358-copy-clean'))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://docs.example.com/guide'))
    expect(screen.getByText(/净链接将移除/)).toBeTruthy()
  })

  it('稍后打开切换 + 清单打开/移除（window.open spy；零 fetch）', () => {
    const openSpy = vi.fn()
    vi.stubGlobal('open', openSpy)
    render(<LinkActionSheet url="https://later.example/post" onClose={() => {}} />)
    fireEvent.click(screen.getByTestId('n358-later'))
    expect(readLinkLater().map((i) => i.url)).toEqual(['https://later.example/post'])
    expect(screen.getByText(/稍后打开（本机 1）/)).toBeTruthy()
    // 清单内立即打开（用户显式点击才发生）
    fireEvent.click(screen.getByRole('button', { name: '立即打开 later.example' }))
    expect(openSpy).toHaveBeenCalledWith('https://later.example/post', '_blank', 'noopener,noreferrer')
    // 切换为移出
    fireEvent.click(screen.getByTestId('n358-later'))
    expect(readLinkLater()).toEqual([])
    expect(screen.queryByRole('button', { name: '立即打开 later.example' })).toBeNull()
    expect(vi.mocked(fetch as unknown as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
  })

  it('剪藏按钮：预填 + 跳转剪藏 section；自身零远端请求', () => {
    render(<LinkActionSheet url="https://clip.example/x" onClose={() => {}} />)
    fireEvent.click(screen.getByTestId('n358-clip'))
    expect(window.sessionStorage.getItem(CLIP_PREFILL_SESSION_KEY)).toBe('https://clip.example/x')
    expect(useReaderUi.getState().section).toBe('clips')
  })
})

describe('NEW-358 长按手势', () => {
  function GestureHost({ href }: { href: string }) {
    const ref = useRef<HTMLDivElement>(null)
    return (
      <div ref={ref} data-testid="n358-host">
        <a href={href} target="_blank" rel="noopener noreferrer">
          外链文字
        </a>
        <LinkActionGesture containerRef={ref} />
      </div>
    )
  }

  it('长按 550ms 外链 → 弹出操作面板；轻点不弹', () => {
    vi.useFakeTimers()
    try {
      render(<GestureHost href="https://out.example/post" />)
      const anchor = screen.getByText('外链文字')
      fireEvent.touchStart(anchor, { touches: [{ clientX: 10, clientY: 10 }] })
      // 未到时长 → 不弹
      act(() => {
        vi.advanceTimersByTime(LINK_LONG_PRESS_MS - 50)
      })
      expect(screen.queryByRole('dialog', { name: '链接操作' })).toBeNull()
      act(() => {
        vi.advanceTimersByTime(50)
      })
      expect(screen.getByRole('dialog', { name: '链接操作' })).toBeTruthy()
      expect(screen.getByText('out.example')).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('提前抬起取消；非外链目标（同源）不弹', () => {
    vi.useFakeTimers()
    try {
      render(<GestureHost href={BASE} />)
      const anchor = screen.getByText('外链文字')
      fireEvent.touchStart(anchor, { touches: [{ clientX: 10, clientY: 10 }] })
      fireEvent.touchEnd(anchor, { changedTouches: [{ clientX: 10, clientY: 10 }] })
      act(() => {
        vi.advanceTimersByTime(LINK_LONG_PRESS_MS + 100)
      })
      expect(screen.queryByRole('dialog', { name: '链接操作' })).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
