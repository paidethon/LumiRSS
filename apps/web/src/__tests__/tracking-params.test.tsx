/** F010 外链追踪参数清理 —— util 单元 + 外链菜单与预览对话框交互。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { isTrackingParam, stripTrackingParams } from '../lib/tracking-params'
import ArticleContent from '../components/ArticleContent'
import { useAppSettings, DEFAULT_APP_SETTINGS } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

describe('F010 stripTrackingParams 单元', () => {
  it('F010: 多参数混合（追踪/未知/签名）——只移除名册内参数', () => {
    const input =
      'https://a.example/p?utm_source=weibo&id=7&utm_medium=social&token=abc&fbclid=IwAR&flag'
    const { url, removed } = stripTrackingParams(input)
    expect(removed.sort()).toEqual(['fbclid', 'utm_medium', 'utm_source'])
    expect(url).toContain('id=7')
    expect(url).toContain('token=abc')
    expect(url).toContain('flag')
    expect(url).not.toContain('utm_source')
    expect(url).not.toContain('fbclid')
  })

  it('F010: 签名类参数绝不删除（token/sig/*_signature/access_token）', () => {
    const input = 'https://s.example/dl?file=a&sig=deadbeef&x_signature=z&access_token=t&gclid=x'
    const { url, removed } = stripTrackingParams(input)
    expect(removed).toEqual(['gclid'])
    expect(url).toContain('sig=deadbeef')
    expect(url).toContain('x_signature=z')
    expect(url).toContain('access_token=t')
  })

  it('F010: CJK 查询值保留；无参数 URL 原样返回', () => {
    const cjk = stripTrackingParams('https://b.example/s?utm_term=摄影&q=镜头')
    expect(cjk.removed).toEqual(['utm_term'])
    expect(cjk.url).toContain('q=')
    expect(decodeURIComponent(cjk.url)).toContain('镜头')

    const plain = 'https://c.example/feed'
    expect(stripTrackingParams(plain)).toEqual({ url: plain, removed: [] })
  })

  it('F010: 非法 URL / 非 http(s) 原样返回（保守）', () => {
    expect(stripTrackingParams('notaurl?utm_source=x').removed).toEqual([])
    expect(stripTrackingParams('javascript:alert(1)?utm_source=x').removed).toEqual([])
    expect(isTrackingParam('UTM_CAMPAIGN')).toBe(true)
  })
})

// ---- 组件入口（外链右键菜单 + 预览对话框） ----

const ARTICLE_HTML =
  '<p>正文 <a href="https://out.example/landing?utm_source=rss&id=9&gclid=zz">外部链接</a></p>'

function detail(): EntryDetail {
  return {
    entryRef: 'e1.f10',
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

function renderArticle() {
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={detail()} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
})

describe('F010 外链菜单与预览', () => {
  it('F010: 右键外链 → 菜单 → 复制干净链接 → 预览列出将移除参数 → 确认写入剪贴板', async () => {
    renderArticle()
    const link = screen.getByText('外部链接')
    fireEvent.contextMenu(link)

    const menu = screen.getByRole('menu', { name: '链接操作' })
    expect(menu).toBeTruthy()
    fireEvent.click(screen.getByTestId('copy-clean-link'))

    // 预览：最小差异（将移除的参数列表）
    const removed = await screen.findByTestId('removed-params')
    expect(removed.textContent).toContain('utm_source')
    expect(removed.textContent).toContain('gclid')
    expect(Array.from(removed.children).every((li) => li.textContent !== 'id')).toBe(true)
    expect(screen.getByTestId('clean-url-preview').textContent).toContain('id=9')
    expect(screen.getByTestId('clean-url-preview').textContent).not.toContain('utm_source=')

    fireEvent.click(screen.getByRole('button', { name: /确认复制/ }))
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        expect.stringContaining('https://out.example/landing'),
      )
    })
    const written = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string
    expect(written).not.toContain('utm_source')
    expect(written).not.toContain('gclid')
    expect(written).toContain('id=9')
  })

  it('F010: 预览取消 → 不写剪贴板；「复制链接」保留原始 URL', async () => {
    renderArticle()
    fireEvent.contextMenu(screen.getByText('外部链接'))
    fireEvent.click(screen.getByTestId('copy-clean-link'))
    // 取消
    fireEvent.click(await screen.findByRole('button', { name: '取消' }))
    expect(screen.queryByText('复制干净链接')).toBeNull()
    expect(navigator.clipboard.writeText).not.toHaveBeenCalled()

    // 原始复制动作不受影响
    fireEvent.contextMenu(screen.getByText('外部链接'))
    fireEvent.click(screen.getByRole('menuitem', { name: '复制链接' }))
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled())
    expect((navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock.calls[0]![0]).toContain('utm_source=rss')
  })
})
