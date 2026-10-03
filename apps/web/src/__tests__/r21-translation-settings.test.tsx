/** R21 翻译设置重写测试（TranslationSettingsSection）。
 *
 * 覆盖：LibreTranslate UI 全部移除（无字样、引擎只有 AI/浏览器两种）、
 * 浏览器翻译运行时探测不可用时选项禁用、迁移横幅两态
 * （translationMigratedFromLibre=true 显示 → 确认后 PATCH 写回 false）。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TranslationSettingsSection } from '../components/settings/TranslationSettingsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response

const AI_SETTINGS = {
  baseUrl: '',
  configured: false,
  defaultKeyConfigured: false,
  envKeyConfigured: false,
  model: 'default-model',
  provider: 'openai_compatible',
  purposeStatus: { translation: { profileId: 'default', keyConfigured: true } },
  purposes: {},
  quotaMaxCalls: 0,
  quotaWindow: '',
  summaryLanguage: 'zh-CN',
  translationEngine: 'ai',
  translationLanguage: 'zh-CN',
}

const PROFILES = [
  {
    id: 'p1',
    label: '轻量摘要',
    baseUrl: 'https://ai.example.internal/v1',
    model: 'qwen-7b',
    provider: 'openai_compatible',
    enabled: true,
    keyConfigured: true,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  },
]

function renderSection(handler: Handler) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      Promise.resolve(handler(String(input), init)),
    ),
  )
  render(
    <QueryClientProvider client={qc}>
      <TranslationSettingsSection />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function baseHandler(serverSettings: Record<string, unknown>): Handler {
  return (url, init) => {
    if (url === '/api/v1/settings' && (init?.method === undefined || init.method === 'GET')) {
      return jsonResponse({ revision: 1, ...serverSettings })
    }
    if (url === '/api/v1/settings' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      return jsonResponse({ revision: 2, ...serverSettings, ...body })
    }
    if (url === '/api/v1/settings/ai') return jsonResponse(AI_SETTINGS)
    if (url === '/api/v1/settings/ai/profiles') return jsonResponse(PROFILES)
    return jsonResponse({ error: { type: 'not_found', message: url } }, 404)
  }
}

describe('翻译设置（R21）', () => {
  it('无任何 LibreTranslate 字样；翻译方式只有 AI / 浏览器两种', async () => {
    renderSection(baseHandler({ translationMigratedFromLibre: false }))
    await screen.findByLabelText('翻译方式')
    expect(document.body.textContent).not.toMatch(/LibreTranslate|libretranslate/i)
    const options = Array.from(screen.getByLabelText('翻译方式').querySelectorAll('option'))
    expect(options).toHaveLength(2)
    expect(options.map((o) => o.value).sort()).toEqual(['ai', 'browser'])
    // AI Profile 可选（默认配置 + 启用的 Profile）
    const profileOptions = Array.from(screen.getByLabelText('翻译 Profile').querySelectorAll('option'))
    expect(profileOptions.map((o) => o.textContent)).toEqual([
      '默认配置（默认模型与密钥）',
      '轻量摘要（qwen-7b）',
    ])
  })

  it('迁移横幅：translationMigratedFromLibre=true 显示说明条 → 确认后 PATCH 写回 false 并消失', async () => {
    const patchBodies: unknown[] = []
    renderSection((url, init) => {
      if (url === '/api/v1/settings' && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        patchBodies.push(body)
        return jsonResponse({ revision: 2, translationMigratedFromLibre: false })
      }
      return baseHandler({ translationMigratedFromLibre: true })(url, init)
    })

    expect(await screen.findByText(/自托管翻译已移除，请选择 AI 或浏览器翻译/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '知道了' }))
    await waitFor(() => {
      expect(patchBodies).toEqual([{ translationMigratedFromLibre: false }])
    })
    await waitFor(() => {
      expect(screen.queryByText(/自托管翻译已移除/)).toBeNull()
    })
  })

  it('迁移横幅：translationMigratedFromLibre=false 不显示', async () => {
    renderSection(baseHandler({ translationMigratedFromLibre: false }))
    await screen.findByLabelText('翻译方式')
    expect(screen.queryByText(/自托管翻译已移除/)).toBeNull()
    expect(screen.queryByRole('button', { name: '知道了' })).toBeNull()
  })

  it('浏览器翻译：运行时探测不可用（jsdom 无 Translator API）→ 选项禁用 + 诚实说明', async () => {
    renderSection(baseHandler({ translationMigratedFromLibre: false }))
    await screen.findByLabelText('翻译方式')
    const browserOption = screen
      .getByLabelText('翻译方式')
      .querySelector('option[value="browser"]') as HTMLOptionElement
    expect(browserOption.disabled).toBe(true)
    expect(browserOption.textContent).toContain('此浏览器不支持')
  })

  it('按需行为说明保留：打开文章不自动翻译', async () => {
    renderSection(baseHandler({ translationMigratedFromLibre: false }))
    await screen.findByLabelText('翻译方式')
    expect(screen.getByText(/打开文章绝不自动翻译/)).toBeInTheDocument()
  })
})
