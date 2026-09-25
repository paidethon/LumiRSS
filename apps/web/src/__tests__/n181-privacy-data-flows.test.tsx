/** N181 —— 数据外发清单（Web 层）。
 *
 * 已配置 → 显示目标主机名（仅主机名）；未配置 → 「不发送」；
 * 本机能力（TTS）→ 「仅本机（不外发）」。fetch 全部 stub。
 */

import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PrivacyDataFlowsSection } from '../components/settings/PrivacyDataFlowsSection'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const FLOWS = {
  flows: [
    {
      capability: 'ai-summary',
      configured: true,
      providerHost: 'api.openai.com',
      dataCategories: ['条目标题与正文'],
      local: false,
    },
    {
      capability: 'libretranslate',
      configured: false,
      providerHost: null,
      dataCategories: [],
      local: false,
    },
    {
      capability: 'tts',
      configured: true,
      providerHost: null,
      dataCategories: ['当前朗读文本（仅在本机合成语音）'],
      local: true,
    },
  ],
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const fetchMock = vi.fn().mockImplementation(async () => jsonResponse(FLOWS))
  vi.stubGlobal('fetch', fetchMock)
  render(
    <QueryClientProvider client={qc}>
      <PrivacyDataFlowsSection />
    </QueryClientProvider>,
  )
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('N181 数据外发清单', () => {
  it('已配置能力显示主机名（仅 hostname），未配置显示「不发送」', async () => {
    renderSection()
    await screen.findByText('AI 摘要')
    const ai = document.querySelector('[data-data-flow="ai-summary"]')
    expect(ai?.textContent).toContain('api.openai.com')
    expect(ai?.textContent).not.toContain('https://') // 只显示主机名，不显示完整 URL
    const libre = document.querySelector('[data-data-flow="libretranslate"]')
    expect(libre?.querySelector('[data-flow-disabled]')?.textContent).toBe('不发送')
    expect(libre?.textContent).not.toContain('发送到')
  })

  it('本机能力（TTS）标注「仅本机（不外发）」，不显示主机名', async () => {
    renderSection()
    await screen.findByText('语音朗读（TTS）')
    const tts = document.querySelector('[data-data-flow="tts"]')
    expect(tts?.querySelector('[data-flow-configured]')?.textContent).toBe('仅本机（不外发）')
  })
})
