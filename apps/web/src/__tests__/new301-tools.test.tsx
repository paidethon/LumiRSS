/** 接入中心（IntakeCenter）测试 — 聚合入口只含收发侧工具；死信重试
 * 仅在存在失败记录时出现；用户可见文案不含开发编号（渲染输出断言
 * 无 /NEW-\d/）。fetch 按 URL 匹配 mock（服务真源在 BFF：
 * services/bff/tests/test_new30*.py、test_new310*.py）。 */

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { IntakeCenter } from '../components/new301/New301IntakeTools'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string) => boolean
  respond: () => Response
}[] = []

function mockRoute(match: (url: string) => boolean, body: unknown, status = 200): void {
  routes.push({ match, respond: () => jsonResponse(body, status) })
}

function renderCenter(): HTMLElement {
  return render(<IntakeCenter />).container
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url)) return route.respond()
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('接入中心（IntakeCenter）', () => {
  it('渲染自然语言分组标题；渲染输出不含开发编号', async () => {
    mockRoute((url) => url.includes('/webhooks/dead-letters'), { items: [] })
    const container = renderCenter()
    expect(screen.getByText('Webhook 收件箱（先审阅再入库）')).toBeTruthy()
    expect(screen.getByText('外发事件订阅')).toBeTruthy()
    expect(screen.getByText('投递回执')).toBeTruthy()
    await waitFor(() => {
      expect(fetchCalls.some((call) => call.url.includes('/webhooks/dead-letters'))).toBe(true)
    })
    // 开发编号不出现在任何用户可见文本
    expect(/NEW-\d/.test(container.textContent ?? '')).toBe(false)
  })

  it('死信为空：死信重试整节不显示（仅存在失败记录才显示）', async () => {
    mockRoute((url) => url.includes('/webhooks/dead-letters'), { items: [] })
    renderCenter()
    await waitFor(() => {
      expect(fetchCalls.some((call) => call.url.includes('/webhooks/dead-letters'))).toBe(true)
    })
    expect(screen.queryByText('死信重试（脱敏重放）')).toBeNull()
  })

  it('存在死信：死信重试节出现；展开 Webhook 收件箱 → 待确认条目可拒绝', async () => {
    mockRoute(
      (url) => url.includes('/webhooks/dead-letters'),
      {
        items: [
          {
            id: 9,
            endpointUuid: 'ep-1',
            eventId: 'evt-9',
            reason: 'invalid_payload',
            payloadSummary: { keys: ['id'], bytes: 120 },
            status: 'pending',
            failedAt: 'now',
            replayedAt: null,
          },
        ],
      },
    )
    mockRoute((url) => url.includes('/webhooks/endpoints'), { items: [] })
    mockRoute(
      (url) => url.includes('/webhooks/inbox'),
      {
        items: [
          {
            id: 5,
            endpointUuid: 'ep-1',
            eventId: 'evt-1:i1',
            title: '待审条目',
            summary: '摘要文本',
            status: 'pending',
            receivedAt: 'now',
            decidedAt: null,
          },
        ],
      },
    )
    renderCenter()
    expect(await screen.findByText('死信重试（脱敏重放）')).toBeTruthy()

    // 展开收件箱（折叠态零请求）
    expect(fetchCalls.some((call) => call.url.includes('/webhooks/inbox'))).toBe(false)
    fireEvent.click(screen.getByText('Webhook 收件箱（先审阅再入库）'))
    const rejectButton = await screen.findByRole('button', { name: '拒绝' })
    fireEvent.click(rejectButton)
    await waitFor(() => {
      expect(
        fetchCalls.some((call) => call.url.endsWith('/webhooks/inbox/5/reject')),
      ).toBe(true)
    })
  })
})
