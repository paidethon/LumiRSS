/** FIX-098 — 浏览器缩放/窄分屏下顶栏操作不溢出、不覆盖标题（结构守卫）。
 *
 * 裁决：BASELINE_OK。ReaderHeader 工具栏的防溢出形态：
 * - 动作容器是 `flex flex-wrap`：宽度不足（缩放/窄分屏/窄列）时动作
 *   **换行**而不是横向溢出——几何上不可能覆盖标题（标题在工具栏之前的
 *   独立块级流内，h1 自带 break-words，长 token 在容器内折行不撑破列）；
 * - 元信息行 `flex min-w-0 flex-wrap`，各段 min-w-0/truncate 逐段让位；
 * - <lg（含缩放落入 lg 以下的视口像素宽）走 O127：非 primary 动作收进
 *   「更多操作」菜单（收纳语义），primary 动作保留——该序与锁定语义由
 *   p07-reader-toolbar.test.tsx 既有套件钉住（本批次运行其作为旁证）。
 *
 * 浏览器缩放/分屏下的真实换行观感依赖渲染几何，jsdom 无法验证——
 * 需浏览器视觉验证，此处如实标注。本守卫钉住 jsdom 可验证的结构契约。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderHeader from '../components/ReaderHeader'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

function detailFixture(): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '一篇标题很长的文章——浏览器缩放时标题应当在容器内折行而不是被工具栏盖住',
    feedTitle: '示例源',
    author: '作者甲',
    url: 'https://example.com/a',
    publishedAt: '2026-09-01T08:00:00Z',
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
  }
}

const callbacks = {
  onViewModeChange: () => {},
  onOpenAiConversation: () => {},
  onOpenFind: () => {},
  onOpenLinks: () => {},
  collectSpeechBlocks: () => ({ texts: ['第一段正文'], startIndex: 0 }),
  onAutoScrollToggle: () => {},
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('FIX-098: 顶栏操作防溢出结构', () => {
  it('动作容器 flex-wrap（溢出即换行，几何上不可能覆盖标题）', () => {
    render(
      withProviders(<ReaderHeader detail={detailFixture()} {...callbacks} />),
    )
    const toolbar = document.querySelector('.mt-4.flex.flex-wrap.items-center') as HTMLElement | null
    expect(toolbar).not.toBeNull()
    expect(toolbar!.className).toContain('flex-wrap')
  })

  it('标题 h1 break-words：长 token 在容器内折行，不横向撑破阅读列', () => {
    render(
      withProviders(<ReaderHeader detail={detailFixture()} {...callbacks} />),
    )
    const title = document.querySelector('header h1') as HTMLElement | null
    expect(title).not.toBeNull()
    expect(title!.className).toContain('break-words')
  })

  it('元信息行 flex-wrap + min-w-0（逐段让位，不与标题争宽度）', () => {
    render(
      withProviders(<ReaderHeader detail={detailFixture()} {...callbacks} />),
    )
    const meta = document.querySelector('header p') as HTMLElement | null
    expect(meta).not.toBeNull()
    expect(meta!.className).toContain('flex-wrap')
    expect(meta!.className).toContain('min-w-0')
  })

  it('窄断点收纳（O127）：非 primary 动作位于 max-lg:hidden 折叠组，「更多操作」恒可达', () => {
    render(
      withProviders(<ReaderHeader detail={detailFixture()} {...callbacks} />),
    )
    // 折叠组：桌面 DOM 平铺（lg:contents）+ 移动端收进菜单（max-lg:hidden）
    const collapsedGroups = document.querySelectorAll('.contents.max-lg\\:hidden')
    expect(collapsedGroups.length).toBeGreaterThan(0)
    // 「更多操作」菜单入口锁定可见（不可被收纳掉）
    expect(screen.getByRole('button', { name: '更多操作' })).toBeInTheDocument()
  })
})
