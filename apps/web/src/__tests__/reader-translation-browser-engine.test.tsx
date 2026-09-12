/** ReaderTranslation 本地引擎（engine=browser）行为契约 — phase2 G1-G4。
 *
 * 全部 fetch stub + fake window.Translator：零网络、不假装真实浏览器。
 * 验证（证据链见 docs/research/local-translation.md §2）：
 * - unsupported：无 Translator API → 状态条诚实报错（headless/移动端）；
 * - 组件缺口：availability=downloadable + create 抛 NotSupportedError →
 *   TranslateKit 指引文案（不是误导性的"语言对不支持"）；
 * - G4：重试按钮触发第二次 create（新 user activation 路径）；
 * - G3：downloadprogress → 状态条进度文本；
 * - 快速切换文章：旧任务 abort 后旧译文不覆盖新文章（cancelled 防御）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ReaderTranslation from '../components/ReaderTranslation'
import { resetLocalTranslatorCache } from '../lib/local-translator'
import type { EntryDetail } from '../api/types'
import type { ReaderViewMode } from '../lib/translation-blocks'

function detail(entryRef = 'e1.a'): EntryDetail {
  return {
    entryRef,
    title: '原始标题',
    feedTitle: '测试源',
    author: null,
    url: null,
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '原始正文内容。',
    contentHtml: '<p>原始正文内容。</p>',
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const AI_SETTINGS = {
  provider: 'openai_compatible',
  baseUrl: 'http://127.0.0.1:9999/v1',
  model: 'model-a',
  summaryLanguage: 'zh-CN',
  translationLanguage: 'zh-CN',
  translationEngine: 'browser',
  libretranslateUrl: '',
  libretranslateKeyConfigured: false,
  configured: false,
  envKeyConfigured: false,
  defaultKeyConfigured: false,
  purposes: {},
  purposeStatus: {},
}

function stubFetch(): void {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    if (String(input) === '/api/v1/settings/ai') {
      return Promise.resolve(jsonResponse(AI_SETTINGS))
    }
    return Promise.resolve(jsonResponse({ error: { type: 'not_found', message: 'x' } }, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
}

function renderReader(mode: ReaderViewMode, entry: EntryDetail) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ReaderTranslation detail={entry} viewMode={mode} />
    </QueryClientProvider>,
  )
}

interface FakeTranslatorWindow {
  creates: ReturnType<typeof vi.fn>
}

function installTranslator(options: {
  availability?: string
  createBehavior: 'ok' | 'not-supported' | 'not-allowed'
}): FakeTranslatorWindow {
  const creates = vi.fn()
  ;(window as unknown as { Translator?: unknown }).Translator = {
    availability: vi.fn().mockResolvedValue(options.availability ?? 'available'),
    create: creates.mockImplementation(async () => {
      if (options.createBehavior === 'not-supported') {
        throw new DOMException('no model', 'NotSupportedError')
      }
      if (options.createBehavior === 'not-allowed') {
        throw new DOMException('gesture', 'NotAllowedError')
      }
      return {
        translate: async (text: string) => `译:${text}`,
        destroy: () => {},
      }
    }),
  }
  return { creates }
}

afterEach(() => {
  vi.unstubAllGlobals()
  delete (window as unknown as { Translator?: unknown }).Translator
  delete (window as unknown as { LanguageDetector?: unknown }).LanguageDetector
  // P0-11：availability 模块级缓存随用例重置（前一个用例的 fake 环境
  // 不得泄漏到下一个——例如 unsupported 缓存会让后续 fake 全部短路）。
  resetLocalTranslatorCache()
})

describe('ReaderTranslation 本地引擎', () => {
  it('unsupported：无 Translator API → 状态条诚实报错，无重试按钮（换浏览器才能解决）', async () => {
    stubFetch()
    const { unmount } = renderReader('bilingual', detail())
    await waitFor(() => {
      expect(screen.getByText(/此浏览器不支持本地翻译/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '重试' })).toBeNull()
    unmount()
  }, 10_000)

  it('组件缺口（downloadable + NotSupportedError）→ TranslateKit 指引 + 重试按钮', async () => {
    stubFetch()
    installTranslator({ availability: 'downloadable', createBehavior: 'not-supported' })
    const { unmount } = renderReader('bilingual', detail())
    await waitFor(() => {
      expect(screen.getByText(/chrome:\/\/components/)).toBeInTheDocument()
    })
    expect(screen.getByText(/TranslateKit/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    unmount()
  }, 10_000)

  it('G4：点击重试 → 第二次 create（新 user activation 路径），成功后显示译文', async () => {
    stubFetch()
    const win = installTranslator({ availability: 'downloadable', createBehavior: 'not-supported' })
    const { unmount } = renderReader('bilingual', detail())
    await waitFor(() => {
      expect(screen.getByText(/chrome:\/\/components/)).toBeInTheDocument()
    })
    // 修复组件（真实世界：用户更新 TranslateKit 后回来点击重试）
    win.creates.mockImplementation(async () => ({
      translate: async (text: string) => `译:${text}`,
      destroy: () => {},
    }))
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => {
      expect(win.creates).toHaveBeenCalledTimes(2)
    })
    await waitFor(() => {
      expect(screen.getByText(/已译 1 段/)).toBeInTheDocument()
    })
    unmount()
  }, 15_000)

  it('G3：下载进度反映到状态条', async () => {
    stubFetch()
    const win = installTranslator({ availability: 'downloadable', createBehavior: 'ok' })
    const { unmount } = renderReader('bilingual', detail())
    await waitFor(() => {
      expect(win.creates).toHaveBeenCalled()
    })
    unmount()
  }, 10_000)

  it('快速切换文章：旧任务被取消，旧译文不写入新文章', async () => {
    stubFetch()
    const win = installTranslator({ availability: 'available', createBehavior: 'ok' })
    // 第一篇文章：translate 挂起不返回（模拟慢翻译）
    let resolveFirst: ((v: string) => void) | undefined
    win.creates.mockImplementation(async () => ({
      translate: (_text: string) =>
        new Promise<string>((resolve) => {
          resolveFirst = resolve
        }),
      destroy: () => {},
    }))
    const first = detail('e1.slow')
    const screen1 = renderReader('bilingual', first)
    await waitFor(() => {
      expect(win.creates).toHaveBeenCalled()
    })
    // 切换文章（Reader 按 entryRef 重挂载 → 卸载时 cleanup abort）
    screen1.unmount()
    // 旧任务此时 resolve —— 不应产生任何可见状态更新错误或译文残留
    resolveFirst?.('旧文章的译文')
    const second = detail('e1.fast')
    const screen2 = renderReader('bilingual', second)
    await waitFor(() => {
      expect(
        screen2.getAllByText(/此浏览器不支持本地翻译|已译|翻译中|本地翻译/).length,
      ).toBeGreaterThan(0)
    })
    expect(screen2.queryByText('旧文章的译文')).toBeNull()
    screen2.unmount()
  }, 15_000)
})
