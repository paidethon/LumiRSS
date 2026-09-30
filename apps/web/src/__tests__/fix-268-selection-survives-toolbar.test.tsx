/**
 * FIX-268 — 工具栏状态更新不重建整篇正文，选择不丢（BASELINE_OK 守卫）。
 *
 * 既有保证（ArticleContent 渲染契约）：
 * - dangerouslySetInnerHTML 的 props 对象经 useMemo 稳定（key =
 *   htmlWithIds 字符串）——React 只在字符串真正变化时才重设 innerHTML；
 * - 与正文输出无关的工具栏开关（如 F15 代码换行、主题、进度显示…）
 *   只触发组件重渲染：正文宿主的同一 <p> DOM 节点原样保留，用户已有
 *   的文本选择（Range）不被清除——复制与标注流程可继续完成。
 *
 * 本守卫钉定该契约：选择正文 → 切换无关工具栏状态 → 断言「同一节点、
 * 选区仍在、复制可用」。防未来把内联字面量塞回 dangerouslySetInnerHTML
 * （每次渲染重设 innerHTML）时无声破坏。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import ArticleContent from '../components/ArticleContent'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

const ARTICLE_HTML = '<p>段落一：可以被选中的正文内容。</p><p>段落二：另一段正文。</p>'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '标题',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-18T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: ARTICLE_HTML,
    contentText: '正文',
  } as unknown as EntryDetail
}

function withProviders(ui: ReactNode): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

let view: ReturnType<typeof render>
let writeText: ReturnType<typeof vi.fn>

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({
    settings: { ...DEFAULT_APP_SETTINGS, readerImageMode: 'all', readerCodeWrap: false },
  })
  writeText = vi.fn(() => Promise.resolve())
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
  vi.stubGlobal('fetch', vi.fn(() => new Response('{}', { status: 200 })))
  view = render(withProviders(<ArticleContent detail={detail()} />))
})

afterEach(() => {
  view?.unmount()
  vi.unstubAllGlobals()
  window.getSelection()?.removeAllRanges()
})

describe('FIX-268: 无关工具栏更新不重建正文、不清选区', () => {
  it('切换代码换行开关后：同一 <p> 节点、选区仍在、复制可完成', async () => {
    // 等管线首帧稳定（sync sanitize 基线已含正文）
    const p1 = await waitFor(() => {
      const p = view.container.querySelector('.article-content p')
      expect(p).not.toBeNull()
      return p as HTMLParagraphElement
    })

    // 用户选中「段落一」内的一段文字
    const textNode = p1.childNodes[0] as Text
    const range = document.createRange()
    range.setStart(textNode, 4)
    range.setEnd(textNode, 12)
    const selection = window.getSelection()
    expect(selection).not.toBeNull()
    act(() => {
      selection!.removeAllRanges()
      selection!.addRange(range)
    })
    const selectedBefore = selection!.toString()
    expect(selectedBefore).toContain('可以')

    // 工具栏状态更新（代码换行开→关无关正文输出；组件因此重渲染）
    act(() => {
      useAppSettings.getState().update({ readerCodeWrap: true })
    })

    // 同一 DOM 节点仍在原位（innerHTML 没有被重设）
    const p1After = view.container.querySelector('.article-content p') as HTMLParagraphElement
    expect(p1After).toBe(p1)
    // 选区原样保留（未被 DOM 重建清除）
    const selectionAfter = window.getSelection()
    expect(selectionAfter!.rangeCount).toBe(1)
    expect(selectionAfter!.toString()).toBe(selectedBefore)
    // 复制流程可继续完成（剪贴板拿到所选文本）
    await act(async () => {
      await navigator.clipboard.writeText(selectionAfter!.toString())
    })
    expect(writeText).toHaveBeenCalledWith(selectedBefore)
  })

  it('被装饰的正文节点跨无关更新保持同一节点（装饰不被抖掉）', async () => {
    // 渲染后装饰（段落复制链接按钮）落在 p 上；无关更新后仍是同一节点
    const decorated = await waitFor(() => {
      const p = view.container.querySelector('.article-content > p')
      expect(p).not.toBeNull()
      return p as HTMLParagraphElement
    })
    await waitFor(() => {
      // 管线 effect + 装饰 effect 完成后，段落带复制链接按钮
      expect(decorated.querySelector('button.lumi-para-link')).not.toBeNull()
    })

    act(() => {
      useAppSettings.getState().update({ readerCodeWrap: true })
    })

    const decoratedAfter = view.container.querySelector('.article-content > p') as HTMLParagraphElement
    expect(decoratedAfter).toBe(decorated)
    // 装饰按钮没有被 innerHTML 重设清掉
    expect(decoratedAfter.querySelector('button.lumi-para-link')).not.toBeNull()
  })
})
