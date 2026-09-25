/** N035 测试 — F044 迁移向导的重定向链展示。
 *
 * 覆盖：校验失败时错误体携带的 redirectChain（掩码 query + 失败跳）；
 * 校验成功且发生重定向时展示 链 + 最终域名；未发生重定向（单跳）时
 * 不渲染链区块。fetch 全部 mock，无真实网络。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MigrateSubscriptionDialog } from '../components/subscription-w3-panels'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function makeFetchHandler(map: Record<string, () => Response>) {
  const fn = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    const handler = map[`POST ${url.split('?')[0]}`]
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${url}`)
    }
    return handler()
  })
  return fn
}

function renderWizard(map: Record<string, () => Response>) {
  vi.stubGlobal('fetch', makeFetchHandler(map))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MigrateSubscriptionDialog
        open
        onClose={() => {}}
        subscriptionRef="s1.ZmVlZC85"
        feedUrl="https://old.example/feed"
        title="旧来源"
      />
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByLabelText('新订阅地址'), {
    target: { value: 'https://new.example/feed' },
  })
  fireEvent.click(screen.getByRole('button', { name: /校验并继续/ }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('F044 — N035 重定向链', () => {
  it('校验失败：错误体附链时展示每一跳（掩码 query）+ 失败跳', async () => {
    renderWizard({
      'POST /api/v1/feed-preview': () =>
        jsonResponse(
          {
            error: {
              type: 'feed_fetch_error',
              message: 'The feed URL answered HTTP 404.',
              redirectChain: [
                { url: 'https://a.example/feed?user=bob', status: 301, final: false },
                { url: 'https://b.example/feed?token=***', status: null, final: false },
              ],
            },
          },
          502,
        ),
    })
    // 停留在第 1 步（校验未通过）
    expect(await screen.findByRole('button', { name: /校验并继续/ })).toBeInTheDocument()
    const chain = await screen.findByRole('group', { name: '重定向链' })
    expect(chain).toBeInTheDocument()
    expect(screen.getByText(/重定向链（2 跳）/)).toBeInTheDocument()
    expect(screen.getByText('https://a.example/feed?user=bob')).toBeInTheDocument()
    // 掩码后的 URL 原样展示；真实凭据值绝不出现
    expect(screen.getByText('https://b.example/feed?token=***')).toBeInTheDocument()
    expect(screen.queryByText(/real-secret/)).not.toBeInTheDocument()
    // 失败跳：请求未完成
    expect(screen.getByText(/失败跳：请求未完成/)).toBeInTheDocument()
    expect(screen.getByText('HTTP 301')).toBeInTheDocument()
  })

  it('校验成功且发生重定向：展示链 + 最终域名', async () => {
    renderWizard({
      'POST /api/v1/feed-preview': () =>
        jsonResponse({
          title: 'New Feed',
          feedUrl: 'https://b.example/feed',
          siteUrl: null,
          description: null,
          format: 'rss',
          alreadySubscribed: false,
          redirectChain: [
            { url: 'https://a.example/feed', status: 301, final: false },
            { url: 'https://b.example/feed', status: 200, final: true },
          ],
        }),
    })
    expect(await screen.findByText(/新地址可达且为有效 feed/)).toBeInTheDocument()
    expect(screen.getByText(/重定向链（2 跳）/)).toBeInTheDocument()
    expect(screen.getByText('最终域名：b.example')).toBeInTheDocument()
    expect(screen.getByText(/最终地址/)).toBeInTheDocument()
  })

  it('校验成功且未重定向（单跳链）：不渲染链区块', async () => {
    renderWizard({
      'POST /api/v1/feed-preview': () =>
        jsonResponse({
          title: 'New Feed',
          feedUrl: 'https://new.example/feed',
          siteUrl: null,
          description: null,
          format: 'rss',
          alreadySubscribed: false,
          redirectChain: [{ url: 'https://new.example/feed', status: 200, final: true }],
        }),
    })
    expect(await screen.findByText(/新地址可达且为有效 feed/)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '重定向链' })).not.toBeInTheDocument()
  })
})
