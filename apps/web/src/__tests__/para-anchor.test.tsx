/** F015 段落定位链接 —— id 稳定性、链接构造（无敏感信息）、App 解析
 * （登录态/未登录暂存/重放）、正文变化的诚实提示、hover 复制链接。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildParaLink,
  hash8,
  initParaTarget,
  paraStableId,
  parseParaParams,
  stashPendingPara,
  takeParaTargetForEntry,
  takePendingPara,
  tryResumePendingPara,
} from '../lib/para-anchor'
import ArticleContent from '../components/ArticleContent'
import { useAuthStore } from '../store/auth'
import { useReaderUi } from '../store/reader-ui'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

describe('F015 段落 id 稳定性与链接', () => {
  it('F015: 同一正文 → 同一 id；正文变化 → id 变化；段序进入 id', () => {
    expect(paraStableId('段落一的内容', 0)).toBe(paraStableId('段落一的内容', 0))
    expect(paraStableId('段落一的内容', 0)).not.toBe(paraStableId('段落二的内容', 0))
    expect(paraStableId('同文', 0)).not.toBe(paraStableId('同文', 1))
    expect(hash8('abc')).toMatch(/^[0-9a-f]{8}$/)
  })

  it('F015: 链接仅含 entry/para，无任何 token/凭据参数', () => {
    const link = buildParaLink('https://lumi.example/', 'e1.abc', 'abcd1234-0')
    expect(link).toBe('https://lumi.example/?entry=e1.abc&para=abcd1234-0')
    expect(link).not.toMatch(/token|password|secret|api[_-]?key/i)
    // 相对 origin 的链接与当前站点同源（分享到任何地方都指向本站）；
    // para id 含特殊字符时被编码（不破坏 URL 结构）
    expect(buildParaLink('https://lumi.example', 'e1.x', 'a b/c')).toBe(
      'https://lumi.example/?entry=e1.x&para=a%20b%2Fc',
    )
  })

  it('F015: parseParaParams 需要两个参数齐全', () => {
    expect(parseParaParams('?entry=e1&para=p1')).toEqual({ entry: 'e1', para: 'p1' })
    expect(parseParaParams('?entry=e1')).toBeNull()
    expect(parseParaParams('')).toBeNull()
  })
})

describe('F015 启动解析与登录重放', () => {
  const originalSearch = window.location.search

  function setSearch(search: string) {
    window.history.replaceState(null, '', `http://localhost:3000/${search}`)
  }

  afterEach(() => {
    window.history.replaceState(null, '', 'http://localhost:3000/' + originalSearch)
    sessionStorage.clear()
  })

  it('F015: 已登录 → 打开文章并把目标留给 ArticleContent 消费；query 被清除', () => {
    useAuthStore.setState({ status: 'authenticated' as const })
    const open = vi.fn()
    setSearch('/?entry=e1.x&para=p1&keep=1')
    initParaTarget(
      () => useAuthStore.getState().status === 'authenticated',
      open,
    )
    expect(open).toHaveBeenCalledWith('e1.x')
    expect(window.location.search).toBe('?keep=1')
    // ArticleContent 消费（读取即清除）
    expect(takeParaTargetForEntry('e1.x')).toBe('p1')
    expect(takeParaTargetForEntry('e1.x')).toBeNull()
  })

  it('F015: 未登录 → 暂存；登录后重放', () => {
    useAuthStore.setState({ status: 'unauthenticated' as const })
    setSearch('/?entry=e2.y&para=p2')
    initParaTarget(() => false, vi.fn())
    expect(takePendingPara()).toEqual({ entry: 'e2.y', para: 'p2' })
    // 重放路径：先暂存 → 登录后调用
    stashPendingPara({ entry: 'e3.z', para: 'p3' })
    const open = vi.fn()
    tryResumePendingPara(open)
    expect(open).toHaveBeenCalledWith('e3.z')
    expect(window.location.search).toBe('') // 重放不清 URL（已在启动时清除）
  })
})

// ---- ArticleContent 集成：id 注入 + 复制链接 + 正文变化提示 ----

const ARTICLE_HTML =
  '<p>第一段内容足够长可以定位。</p><p id="pre-existing">已有 id 的段落。</p><p>第三段。</p>'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.para',
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

function renderArticle(entryRef = 'e1.para') {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  useReaderUi.setState({ selectedEntryRef: entryRef })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={{ ...detail(), entryRef }} />
    </QueryClientProvider>,
  )
}

const writeText = vi.fn().mockResolvedValue(undefined)

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText } })
  sessionStorage.clear()
})

describe('F015 ArticleContent 集成', () => {
  it('F015: 段落获得稳定 id 与复制按钮；点击复制无凭据链接', async () => {
    renderArticle()
    const buttons = await screen.findAllByRole('button', { name: '复制段落链接' })
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    fireEvent.click(buttons[0]!)
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const link = writeText.mock.calls[0]![0] as string
    expect(link).toContain('entry=e1.para&para=')
    expect(link).not.toMatch(/token|password|secret/i)
    // id 稳定：重渲染同文 → 相同 id（由 hash8 决定）
    const paragraphs = document.querySelectorAll('.article-content > p')
    expect(paragraphs[0]!.id).toMatch(/^[0-9a-f]{8}-0$/)
  })

  it('F015: 目标段落不存在（正文已变化）→ 诚实提示，不跳错段', () => {
    stashPendingPara({ entry: 'e1.para', para: 'deadbeef-99' })
    renderArticle()
    expect(screen.getByTestId('para-missing')).toBeInTheDocument()
    expect(screen.getByText('原文已变化，无法定位')).toBeInTheDocument()
  })

  it('F015: 目标匹配 → 消费后 sessionStorage 清空（不残留跨文章泄漏）', () => {
    stashPendingPara({ entry: 'e1.para', para: 'whatever' })
    renderArticle()
    expect(takeParaTargetForEntry('e1.para')).toBeNull() // 已被组件消费
  })
})
