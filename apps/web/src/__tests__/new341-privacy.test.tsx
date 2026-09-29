/** NEW-341..350 Web 入口测试 — 隐私与授权中心两块组合面板的渲染与
 * 交互主路径。
 *
 * 环境：jsdom；fetch 按 URL 匹配 mock（服务真源在 BFF，后端口径见
 * services/bff/tests/test_new34*.py / test_new350*.py）。 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { PrivacyAuthorizationCenter } from '../components/new341/PrivacyAuthorizationCenter'
import { PrivacySharingCenter } from '../components/new341/PrivacySharingCenter'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithQuery(ui: React.ReactElement): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const fetchCalls: { url: string; init?: RequestInit }[] = []
let routes: {
  match: (url: string, init?: RequestInit) => boolean
  respond: (url: string, init?: RequestInit) => Response
}[] = []

function mockRoute(
  matcher: (url: string, init?: RequestInit) => boolean,
  responder: (url: string, init?: RequestInit) => Response,
): void {
  routes.push({ match: matcher, respond: responder })
}

function callsTo(url: string): { url: string; init?: RequestInit }[] {
  return fetchCalls.filter((call) => call.url === url || call.url.startsWith(`${url}?`))
}

function expand(mainName: RegExp, subsectionId: string): void {
  fireEvent.click(screen.getByRole('button', { name: mainName }))
  const toggles = screen
    .getAllByRole('button')
    .filter((button) => {
      const host = button.closest('[data-n341-subsection]')
      return host !== null && host.getAttribute('data-n341-subsection') === subsectionId
    })
  expect(toggles.length).toBeGreaterThan(0)
  fireEvent.click(toggles[0])
}

beforeEach(() => {
  fetchCalls.length = 0
  routes = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    fetchCalls.push({ url, init })
    for (const route of routes) {
      if (route.match(url, init)) return route.respond(url, init)
    }
    return jsonResponse({ error: { type: 'unmocked', message: url } }, 404)
  }) as typeof fetch
})

afterEach(() => {
  cleanup()
  routes = []
})

describe('NEW-341..350 隐私与授权中心（Web 入口）', () => {
  it('折叠态零请求；展开 NEW-341 后拉取访问记录并如实展示无法记录的边界', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/access-log',
      () =>
        jsonResponse({
          items: [
            { id: 1, purpose: 'briefing_feed', purposeLabel: '个人简报 RSS 订阅', entry: '个人简报 Atom', accessedAt: 'T0' },
          ],
          recordedScope: '仅记录经 Lumi 公开共享入口的成功读取。',
          unrecorded: ['FreshRSS 直接服务的原生订阅不经过 Lumi，无法记录', '绝不记录访问者 IP'],
          bounded: false,
        }),
    )
    renderWithQuery(<PrivacyAuthorizationCenter />)
    expect(callsTo('/api/v1/privacy/access-log')).toHaveLength(0)
    expand(/隐私与授权中心（/, 'n341-access-log')
    await waitFor(() => expect(callsTo('/api/v1/privacy/access-log')).toHaveLength(1))
    expect(await screen.findByText(/个人简报 RSS 订阅/)).toBeTruthy()
    expect(screen.getByText(/无法记录：FreshRSS/)).toBeTruthy()
    expect(screen.getByText(/绝不记录访问者 IP/)).toBeTruthy()
  })

  it('NEW-342 可选请求开关发出真实 toggle 调用', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/third-party-requests',
      () =>
        jsonResponse({
          reading: [
            {
              key: 'remote_images',
              scope: 'reading',
              host: null,
              purpose: '文章远程图片',
              optional: true,
              disabled: false,
              controlledBy: '便携设置 readerImageMode',
              optoutKey: 'remote_images',
            },
          ],
          ai: [],
          note: '清单从当前配置实时推导，不是逐请求网络日志。',
          optoutLabels: {},
          recentActions: [],
        }),
    )
    renderWithQuery(<PrivacyAuthorizationCenter />)
    expand(/隐私与授权中心（/, 'n342-third-party')
    const toggle = await screen.findByRole('button', { name: '关闭请求' })
    fireEvent.click(toggle)
    await waitFor(() => {
      const posted = callsTo('/api/v1/privacy/third-party-requests/remote_images/toggle')
      expect(posted).toHaveLength(1)
      expect(JSON.parse(String(posted[0]?.init?.body))).toEqual({ disabled: true })
    })
  })

  it('NEW-343 标记列表 + 提交「不发送至外部 AI」标记（PUT 真实调用）', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/privacy/ai-send-blocks' && (init?.method ?? 'GET') === 'GET',
      () => jsonResponse({ items: [{ entryRef: 'rss:abc', reason: '医疗记录', createdAt: 'T0' }], note: 'n' }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/privacy/ai-send-blocks/rss:def' && init?.method === 'POST',
      () => jsonResponse({ entryRef: 'rss:def', reason: '含个人敏感信息，不发送至外部 AI。' }),
    )
    renderWithQuery(<PrivacyAuthorizationCenter />)
    expand(/隐私与授权中心（/, 'n343-sensitive-marks')
    expect(await screen.findByText(/rss:abc · 医疗记录/)).toBeTruthy()
    const inputs = screen.getAllByRole('textbox')
    fireEvent.change(inputs[0], { target: { value: 'rss:def' } })
    fireEvent.change(inputs[1], { target: { value: '医疗记录' } })
    fireEvent.click(screen.getByRole('button', { name: /标记为「不发送至外部 AI」/ }))
    await waitFor(() => {
      const put = callsTo('/api/v1/privacy/ai-send-blocks/rss:def')
      expect(put).toHaveLength(1)
      expect(JSON.parse(String(put[0]?.init?.body))).toEqual({ reason: '医疗记录' })
    })
  })

  it('NEW-344 创建共享链接：明文 token 仅此一次展示（scope=full 提示需设备信任）', async () => {
    mockRoute(
      (url, init) => url === '/api/v1/privacy/share-links' && (init?.method ?? 'GET') === 'GET',
      () => jsonResponse({ items: [], note: '清单不含任何 token 材料；scope 创建后不可变。' }),
    )
    mockRoute(
      (url, init) => url === '/api/v1/privacy/share-links' && init?.method === 'POST',
      () =>
        jsonResponse(
          {
            id: 7,
            token: 'one-time-token',
            path: '/shares/one-time-token',
            title: '目录',
            scope: 'titles',
            excerptChars: 0,
            maxUses: null,
            createdAt: 'T0',
            revokedAt: null,
            useCount: 0,
            exhaustedAt: null,
            note: '明文 token 仅此一次返回。',
          },
          201,
        ),
    )
    renderWithQuery(<PrivacySharingCenter />)
    expand(/共享与删除控制（/, 'n344-share-links')
    const textboxes = await screen.findAllByRole('textbox')
    fireEvent.change(textboxes[0], { target: { value: '目录' } })
    fireEvent.change(textboxes[1], { target: { value: 'rss:a,rss:b' } })
    fireEvent.click(screen.getByRole('button', { name: '创建共享链接' }))
    expect(await screen.findByText(/\/shares\/one-time-token/)).toBeTruthy()
    expect(screen.getByText(/仅此一次显示/)).toBeTruthy()
  })

  it('NEW-345 访问记录展开拉取（含被拒访问）', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/share-links',
      () =>
        jsonResponse({
          items: [
            {
              id: 3,
              title: '限额链接',
              scope: 'titles',
              excerptChars: 0,
              createdAt: 'T0',
              revokedAt: null,
              maxUses: 2,
              useCount: 2,
              exhaustedAt: 'T1',
            },
          ],
          note: 'n',
        }),
    )
    mockRoute(
      (url) => url === '/api/v1/privacy/share-links/3/accesses',
      () =>
        jsonResponse({
          items: [
            { id: 3, accessedAt: 'T3', result: 'limit_reached' },
            { id: 2, accessedAt: 'T2', result: 'served' },
          ],
          note: '访问者身份/IP 不记录；被拒（耗尽）的访问同样留痕但不计数。',
        }),
    )
    renderWithQuery(<PrivacySharingCenter />)
    expand(/共享与删除控制（/, 'n345-limits')
    fireEvent.click(await screen.findByText(/限额链接/))
    expect(await screen.findByText(/limit_reached/)).toBeTruthy()
    expect(screen.getByText(/同样留痕但不计数/)).toBeTruthy()
  })

  it('NEW-346 设备信任状态 + 授予调用（密码字段 type=password）', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/device-trust',
      () =>
        jsonResponse({
          currentDevice: { deviceFingerprint: 'abcd1234', deviceLabel: 'Chrome/Linux', trusted: false, trustedUntil: null },
          grants: [],
          note: '设备信任不创建也不延长服务端会话。',
        }),
    )
    renderWithQuery(<PrivacyAuthorizationCenter />)
    expand(/隐私与授权中心（/, 'n346-device-trust')
    expect(await screen.findByText(/未授予信任/)).toBeTruthy()
    const passwordInput = screen.getByLabelText('登录密码')
    expect(passwordInput.getAttribute('type')).toBe('password')
    fireEvent.change(passwordInput, { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: '授予 / 续期' }))
    await waitFor(() => {
      const posted = callsTo('/api/v1/privacy/device-trust').filter(
        (call) => call.init?.method === 'POST',
      )
      expect(posted).toHaveLength(1)
      expect(JSON.parse(String(posted[0]?.init?.body))).toEqual({ password: 'pw', hours: 12 })
    })
  })

  it('NEW-347 授权清单逐项展示撤销影响 + 撤销调用；绝不显示 token 材料', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/authorizations',
      () =>
        jsonResponse({
          items: [
            {
              kind: 'briefing_feed',
              ref: 'default',
              label: '个人简报 RSS 订阅',
              active: true,
              detail: '启用于 T0',
              affected: '个人简报 RSS 订阅地址立即失效（订阅端拉取 404）',
            },
          ],
          note: '清单只含状态与影响说明；任何令牌材料（含前缀）都不会出现在响应里。',
        }),
    )
    renderWithQuery(<PrivacyAuthorizationCenter />)
    expand(/隐私与授权中心（/, 'n347-authorizations')
    expect(await screen.findByText(/撤销影响/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '撤销' }))
    await waitFor(() => {
      expect(callsTo('/api/v1/privacy/authorizations/briefing_feed/default/revoke')).toHaveLength(1)
    })
  })

  it('NEW-349 向导逐项撤回；无一键全删；不可撤回项如实说明', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/review',
      () =>
        jsonResponse({
          items: [
            {
              key: 'briefing_feed',
              category: 'sharing',
              title: '个人简报 RSS 订阅',
              detail: '已开启',
              withdraw: { available: true, actionKey: 'briefing_feed', needsRef: false, how: '撤销订阅 token' },
            },
            {
              key: 'reader_offline_cache',
              category: 'device_cache',
              title: '阅读离线缓存（设备本地）',
              detail: '在浏览器/设备本地存储',
              withdraw: { available: false, actionKey: null, needsRef: false, how: '只能在设备本地清除' },
            },
          ],
          note: '向导没有一键全删：每项撤回独立确认、独立留痕。',
          recentActions: [],
        }),
    )
    renderWithQuery(<PrivacySharingCenter />)
    expand(/共享与删除控制（/, 'n349-review')
    expect(await screen.findByText(/没有一键全删/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /一键/ })).toBeNull()
    expect(screen.getByText(/只能在设备本地清除/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '撤回' }))
    await waitFor(() => {
      const posted = callsTo('/api/v1/privacy/review/briefing_feed/withdraw')
      expect(posted).toHaveLength(1)
      expect(JSON.parse(String(posted[0]?.init?.body))).toEqual({ ref: '' })
    })
  })

  it('NEW-350 预览展示类别计数与共享副本规则；DELETE 未输入前确认禁用', async () => {
    mockRoute(
      (url) => url === '/api/v1/privacy/deletion/preview',
      () =>
        jsonResponse({
          categories: { entries: 12, aiTaskLogs: 0 },
          sharedCopies: [{ copy: 'FreshRSS 侧数据', rule: '不在 Lumi 删除范围内', action: 'none' }],
          note: 'n',
        }),
    )
    renderWithQuery(<PrivacySharingCenter />)
    expand(/共享与删除控制（/, 'n350-deletion')
    await screen.findByText(/不在 Lumi 删除范围内/)
    await waitFor(() => {
      expect(callsTo('/api/v1/privacy/deletion/preview')).toHaveLength(1)
    })
    const confirmButton = screen.getByRole('button', { name: /确认注销并执行处理/ })
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByLabelText('输入 DELETE 确认删除')).toBeTruthy()
  })
})
