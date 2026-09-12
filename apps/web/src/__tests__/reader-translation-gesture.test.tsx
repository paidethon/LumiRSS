/** ReaderTranslation 手势编排契约（P0-11 wave 1）。
 *
 * 边界诚实声明：jsdom 没有 Chrome 内置 Translator/LanguageDetector，
 * 也无法验证真实 user activation 的生命周期——真机行为（activation
 * 是否贯穿 create() 的冷启动下载）由 headed-Chrome 矩阵后续验证。
 * 本文件只 unit-test 编排契约：
 * - 手势路径不经过任何 timer（120ms debounce 不在点击链路上），
 *   Translator.create() 是链路里第一个长等待；
 * - 探测结果按文章缓存（第二次点击零 detector 调用）；
 * - 同语言短路：source===target(base) → 零 create()/translate()；
 * - 真英语 vs 探测失败回退可区分（via 判别结果进 UI）。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReaderHeader from '../components/ReaderHeader'
import ReaderTranslation from '../components/ReaderTranslation'
import { resetLocalTranslatorCache } from '../lib/local-translator'
import type { EntryDetail } from '../api/types'

function detail(entryRef = 'e1.g'): EntryDetail {
  return {
    entryRef,
    title: '原始标题',
    feedTitle: '测试源',
    author: null,
    url: null,
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '这是需要翻译的正文内容。',
    contentHtml: '<p>这是需要翻译的正文内容。</p>',
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function aiSettings(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
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
    ...over,
  }
}

function stubAiSettings(settings: Record<string, unknown>): void {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    if (String(input) === '/api/v1/settings/ai') {
      return Promise.resolve(jsonResponse(settings))
    }
    return Promise.resolve(jsonResponse({ error: { type: 'not_found', message: 'x' } }, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
}

interface TranslatorWin {
  creates: ReturnType<typeof vi.fn>
}

function installTranslator(options: {
  availability?: string
  createBehavior?: 'ok' | 'never'
}): TranslatorWin {
  const creates = vi.fn()
  if (options.createBehavior === 'never') {
    creates.mockImplementation(() => new Promise(() => {}))
  } else {
    creates.mockImplementation(async () => ({
      translate: async (text: string) => `译:${text}`,
      destroy: () => {},
    }))
  }
  ;(window as unknown as { Translator?: unknown }).Translator = {
    availability: vi.fn().mockResolvedValue(options.availability ?? 'available'),
    create: creates,
  }
  return { creates }
}

function installDetector(detected: string | 'fail'): ReturnType<typeof vi.fn> {
  const detect = vi.fn(async () => {
    if (detected === 'fail') throw new Error('detector failed')
    return [{ detectedLanguage: detected, confidence: 0.95 }]
  })
  ;(window as unknown as { LanguageDetector?: unknown }).LanguageDetector = {
    create: async () => ({ detect }),
  }
  return detect
}

/** 渲染并捕获注册的手势启动回调（Reader 在语言视图点击事件内调用它）。
 * 直接把引擎设置种进 Query 缓存：engine 在首次渲染即生效（注册的
 * start 回调就是 browser 引擎闭包），点击链路不被设置请求的
 * setTimeout 调度污染——fake timers 下同样确定。 */
function renderWithGesture(entry: EntryDetail, engineSettings: Record<string, unknown>) {
  stubAiSettings(engineSettings)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  queryClient.setQueryData(['ai-settings'], engineSettings)
  let start: (() => void) | null = null
  const screen1 = render(
    <QueryClientProvider client={queryClient}>
      <ReaderTranslation
        detail={entry}
        viewMode="bilingual"
        registerTranslationStart={(fn) => {
          start = fn
        }}
      />
    </QueryClientProvider>,
  )
  return {
    screen: screen1,
    /** 模拟语言视图点击（同步手势任务内调用）。 */
    click: () => {
      act(() => {
        start?.()
      })
    },
  }
}

function flushMicrotasks(): Promise<void> {
  // 只清微任务（不依赖任何 timer；fake timers 下同样安全）。
  return act(async () => {
    for (let i = 0; i < 60; i++) {
      await Promise.resolve()
    }
  })
}

beforeEach(() => {
  resetLocalTranslatorCache()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  delete (window as unknown as { Translator?: unknown }).Translator
  delete (window as unknown as { LanguageDetector?: unknown }).LanguageDetector
  resetLocalTranslatorCache()
})

describe('ReaderTranslation 手势编排（P0-11）', () => {
  it('create 在点击手势内直接启动：fake timers 冻结（observer 的 120ms debounce 永不触发）下 create 仍被调用', async () => {
    // 只冻结 setTimeout/clearTimeout（React 调度器走 MessageChannel，
    // 不受影响）；120ms debounce 依赖 setTimeout → 冻结即永不触发。
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    installDetector('en')
    const win = installTranslator({ availability: 'downloadable', createBehavior: 'never' })
    const { click, screen: screen1 } = renderWithGesture(detail(), aiSettings())
    // 等设置（engine=browser）到位
    await flushMicrotasks()
    click()
    // 只清微任务，不推进 timer——若 create 被调用，说明它不在 timer 链上
    await flushMicrotasks()
    expect(win.creates).toHaveBeenCalledTimes(1)
    expect(win.creates.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ sourceLanguage: 'en', targetLanguage: 'zh-CN' }),
    )
    screen1.unmount()
  })

  it('探测结果按文章缓存：第二次点击零 detector 调用（复用 translator + 探测）', async () => {
    installDetector('en')
    const win = installTranslator({ availability: 'available' })
    const { click, screen: screen1 } = renderWithGesture(detail(), aiSettings())
    await flushMicrotasks()
    click()
    await waitFor(() => {
      expect(screen1.getByText(/已译 1 段/)).toBeInTheDocument()
    })
    click()
    await flushMicrotasks()
    // 真实浏览器矩阵关注点：第二次 create 不应发生（translator 复用）
    expect(win.creates).toHaveBeenCalledTimes(1)
    screen1.unmount()
  })

  it('同语言短路：探测 zh + 目标 zh-CN → 零 create()，诚实提示原文即目标语言', async () => {
    installDetector('zh')
    const win = installTranslator({ availability: 'available' })
    const { click, screen: screen1 } = renderWithGesture(detail(), aiSettings())
    await flushMicrotasks()
    click()
    await waitFor(() => {
      expect(screen1.getByText(/原文即目标语言，无需翻译/)).toBeInTheDocument()
    })
    expect(win.creates).not.toHaveBeenCalled()
    expect(screen1.getByText(/源语言：zh/)).toBeInTheDocument()
    screen1.unmount()
  })

  it('真英语（via=detected）不显示「探测失败回退」；探测失败（via=fallback）才显示', async () => {
    // 真英语：detector 给出 en
    installDetector('en')
    installTranslator({ availability: 'unavailable' }) // create 会失败，但探测展示先行
    const english = renderWithGesture(detail('e1.en'), aiSettings())
    await flushMicrotasks()
    english.click()
    await waitFor(() => {
      expect(english.screen.getByText(/源语言：en/)).toBeInTheDocument()
    })
    expect(english.screen.queryByText(/探测失败回退/)).toBeNull()
    english.screen.unmount()

    // 探测失败：detector 抛错 → fallback
    installDetector('fail')
    installTranslator({ availability: 'unavailable' })
    const fallback = renderWithGesture(detail('e1.fb'), aiSettings())
    await flushMicrotasks()
    fallback.click()
    await waitFor(() => {
      expect(fallback.screen.getByText(/源语言：en/)).toBeInTheDocument()
    })
    expect(fallback.screen.getByText(/探测失败回退/)).toBeInTheDocument()
    fallback.screen.unmount()
  })
})

describe('ReaderHeader 语言视图门控（P0-11）', () => {
  function renderHeader(settings: Record<string, unknown>) {
    stubAiSettings(settings)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    queryClient.setQueryData(['ai-settings'], settings)
    return render(
      <QueryClientProvider client={queryClient}>
        <ReaderHeader
          detail={detail()}
          viewMode="original"
          onViewModeChange={() => {}}
        />
      </QueryClientProvider>,
    )
  }

  it('engine=browser 且无 Translator API → 双语/仅译文禁用并附原因', async () => {
    // 不安装 window.Translator
    const screen1 = renderHeader(aiSettings())
    await waitFor(() => {
      expect(screen1.getByRole('button', { name: '双语' })).toBeDisabled()
    })
    expect(screen1.getByRole('button', { name: '仅译文' })).toBeDisabled()
    expect(screen1.getByRole('button', { name: '双语' })).toHaveAttribute(
      'title',
      expect.stringContaining('不支持本地翻译'),
    )
    screen1.unmount()
  })

  it('engine=browser 且 Translator API 存在 → 控件可用', async () => {
    installTranslator({ availability: 'available' })
    const screen1 = renderHeader(aiSettings())
    await waitFor(() => {
      expect(screen1.getByRole('button', { name: '双语' })).toBeEnabled()
    })
    screen1.unmount()
  })

  it('engine=ai（非浏览器引擎）→ 控件不受本地 Translator 支持性影响', async () => {
    // 无 window.Translator，但 AI 引擎不依赖它
    const screen1 = renderHeader(aiSettings({ translationEngine: 'ai' }))
    await waitFor(() => {
      expect(screen1.getByRole('button', { name: '双语' })).toBeEnabled()
    })
    screen1.unmount()
  })
})
