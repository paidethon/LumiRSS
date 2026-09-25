/** N061/N062 — 图片灯箱：在原文中查看（关闭灯箱 + scrollIntoView 源图
 * + 焦点归还源图）与图片说明提取（figcaption > title > aria-label；
 * 缺失明示「未提供说明」；来源主机名展示；顺序与正文一致）。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ArticleContent from '../components/ArticleContent'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

function detail(overrides: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '图片文章',
    feedTitle: '源',
    author: null,
    url: null,
    publishedAt: '2026-09-24T00:00:00Z',
    read: false,
    starred: false,
    contentHtml: '<p>正文</p>',
    contentText: '正文',
    ...overrides,
  } as unknown as EntryDetail
}

const CONTENT =
  '<p>开头</p>' +
  '<figure><img src="https://cdn.example.com/a.png" alt="图A"><figcaption>图A说明文字</figcaption></figure>' +
  '<p><img src="https://img.example.org/b.png" title="图B标题属性"></p>' +
  '<p><img src="https://cdn.example.com/c.png" aria-label="图C无障碍名"></p>' +
  '<p><img src="https://cdn.example.com/d.png" alt="图D无说明"></p>'

function renderArticle(contentHtml: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <ArticleContent detail={detail({ contentHtml })} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useAppSettings.setState({
    settings: { ...DEFAULT_APP_SETTINGS, readerCodeHighlight: 'off', readerImageMode: 'all' },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

describe('N062 图片说明提取', () => {
  it('figcaption / title / aria-label 依次提取；缺失明示「未提供说明」；来源主机名展示', async () => {
    renderArticle(CONTENT)
    // 打开第一张（figure > figcaption）
    fireEvent.click(await screen.findByRole('img', { name: '图A' }))
    await screen.findByRole('dialog', { name: '图片查看' })
    const caption = () => document.querySelector('[data-testid="lightbox-caption"]')
    expect(caption()!.textContent).toContain('图A说明文字')
    expect(caption()!.textContent).toContain('cdn.example.com')

    // 下一张：title 属性
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption()!.textContent).toContain('图B标题属性'))
    expect(caption()!.textContent).toContain('img.example.org')

    // 下一张：aria-label
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption()!.textContent).toContain('图C无障碍名'))

    // 下一张：全部缺失 → 明示「未提供说明」（不用 alt 冒充说明）
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption()!.textContent).toContain('未提供说明'))
    expect(caption()!.textContent).toContain('cdn.example.com')
  })

  it('说明顺序与正文图片顺序一致（图A → 图B → 图C → 图D）', async () => {
    renderArticle(CONTENT)
    fireEvent.click(await screen.findByRole('img', { name: '图A' }))
    await screen.findByRole('dialog', { name: '图片查看' })
    const caption = () => {
      const el = document.querySelector('[data-testid="lightbox-caption"]')
      expect(el).not.toBeNull()
      return el as HTMLElement
    }
    expect(caption().textContent).toContain('图A说明文字')
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption().textContent).toContain('图B标题属性'))
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption().textContent).toContain('图C无障碍名'))
    fireEvent.click(screen.getByRole('button', { name: '下一张' }))
    await waitFor(() => expect(caption().textContent).toContain('未提供说明'))
    // 计数器与说明区同源：第 4 / 4 张
    expect(document.querySelector('[data-lumi-lightbox-counter]')!.textContent).toBe('4 / 4')
  })
})

describe('N061 在原文中查看', () => {
  it('灯箱提供「在原文中查看」；点击关闭灯箱并 scrollIntoView 源图 + 焦点归还源图', async () => {
    const scrolled: Element[] = []
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this)
    }
    try {
      renderArticle(CONTENT)
      const sourceImg = await screen.findByRole('img', { name: '图A' })
      fireEvent.click(sourceImg)
      await screen.findByRole('dialog', { name: '图片查看' })
      expect(screen.getByRole('button', { name: '在原文中查看' })).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: '在原文中查看' }))
      await waitFor(() => {
        expect(screen.queryByRole('dialog', { name: '图片查看' })).toBeNull()
      })
      // 定位到的正是正文里的源 img 元素
      expect(scrolled).toHaveLength(1)
      expect(scrolled[0]).toBe(sourceImg)
      expect(document.activeElement).toBe(sourceImg)
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })
})
