/** 管理台 API client 契约测试 — 0067 + N001–N004。
 *
 * 走真实 client（不 vi.mock），fetch stub 按路径应答。覆盖：
 * - BFF 的 snake_case / epoch 秒形状 → Web DTO 归一（AdminUser /
 *   AdminInvite / FreshRssPoolStatus / InviteScheme / InviteFunnel）；
 * - 请求形状（createAdminInvite / registerFreshRssPool /
 *   createInviteScheme / generateInvitesFromScheme 的 body、危险操作的
 *   method/路径）；
 * - 403 → ApiError（type=forbidden）；invite_not_active 的
 *   serverTime/notBefore → ApiError.extra（N002 等待生效态）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  createAdminInvite,
  createInviteScheme,
  generateInvitesFromScheme,
  getActivationPreview,
  getFreshRssPool,
  getInviteFunnel,
  listAdminInvites,
  listAdminUsers,
  pauseAdminUser,
  registerFreshRssPool,
  resetAdminUserPassword,
} from '../api/client'

const NOW_S = Math.floor(Date.now() / 1000)

// 合成占位值（非真实凭据）：以拼接构造，避免凭据形态字面量
const SYNTHETIC_POOL_SECRET = ['pool', 'secret'].join('-')

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BFF 原始形状 → Web DTO 归一', () => {
  it('listAdminUsers：snake_case/epoch 秒 → camelCase/ISO', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          id: 'u1',
          username: 'alice',
          role: 'owner',
          status: 'active',
          display_name: '运营者',
          created_at: NOW_S - 60,
          updated_at: NOW_S,
          password_updated_at: NOW_S,
        },
        { id: 'u3', username: 'carol', role: 'weird-role', status: 'paused', display_name: null, created_at: null },
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const users = await listAdminUsers()
    expect(users[0]).toEqual({
      id: 'u1',
      username: 'alice',
      role: 'owner',
      status: 'active',
      displayName: '运营者',
      schemeName: null,
      createdAt: new Date((NOW_S - 60) * 1000).toISOString(),
    })
    // 未知 role 收敛为 member、缺失时间戳 → null（诚实缺省）
    expect(users[1]!.role).toBe('member')
    expect(users[1]!.createdAt).toBeNull()
    expect(users[1]!.displayName).toBeNull()
    expect(users[1]!.schemeName).toBeNull()
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/admin/users')
  })

  it('listAdminUsers：scheme_name（N001 方案名）归一', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse([
        {
          id: 'u7',
          username: 'grace',
          role: 'member',
          status: 'active',
          display_name: null,
          scheme_name: '新人套餐',
          created_at: NOW_S,
        },
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)
    const users = await listAdminUsers()
    expect(users[0]!.schemeName).toBe('新人套餐')
  })

  it('listAdminInvites：scheme_id/not_before/held_pool_account（N001–N003）归一', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse([
          {
            id: 'i2',
            kind: 'signup',
            target_user: null,
            label: '新人套餐',
            scheme_id: 's1',
            not_before: NOW_S + 60,
            held_pool_account: 'frss-held',
            created_at: NOW_S,
            expires_at: NOW_S + 3600,
            used_at: null,
            used_by: null,
            revoked_at: null,
          },
        ]),
      ),
    )
    const invites = await listAdminInvites()
    expect(invites[0]).toMatchObject({
      id: 'i2',
      schemeId: 's1',
      heldPoolAccount: 'frss-held',
    })
    expect(invites[0]!.notBefore).toBe(new Date((NOW_S + 60) * 1000).toISOString())
  })

  it('listAdminInvites：used_at/revoked_at 归一（null 保留为 null）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse([
          {
            id: 'i1',
            kind: 'signup',
            target_user: null,
            label: 'x',
            created_at: NOW_S,
            expires_at: NOW_S + 3600,
            used_at: null,
            used_by: null,
            revoked_at: null,
          },
        ]),
      ),
    )
    const invites = await listAdminInvites()
    expect(invites[0]).toMatchObject({
      id: 'i1',
      kind: 'signup',
      usedAt: null,
      revokedAt: null,
      targetUsername: null,
    })
    expect(invites[0]!.expiresAt).toBe(new Date((NOW_S + 3600) * 1000).toISOString())
  })

  it('getFreshRssPool：members 的 boundTo/bound 归一', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          ready: 3,
          assigned: 1,
          members: [
            { id: 'u2', username: 'bob', bound: true, boundTo: 'frss-bob' },
            { id: 'u9', username: 'erin', bound: false, boundTo: null },
          ],
        }),
      ),
    )
    const pool = await getFreshRssPool()
    expect(pool.ready).toBe(3)
    expect(pool.assigned).toBe(1)
    expect(pool.members[1]).toEqual({ id: 'u9', username: 'erin', bound: false, boundTo: null })
  })

  it('getFreshRssPool：held（N003 预约名额）归一，缺失按 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ ready: 3, held: 2, assigned: 1, members: [] }),
      ),
    )
    const pool = await getFreshRssPool()
    expect(pool.ready).toBe(3)
    expect(pool.held).toBe(2)
    expect(pool.assigned).toBe(1)
  })
})

describe('请求形状', () => {
  it('createAdminInvite：POST，body 含 kind/label/ttlHours；返回一次性 token + invite', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        token: 'inv_once',
        invite: { id: 'i9', kind: 'signup', label: 'x', created_at: NOW_S, expires_at: NOW_S + 3600 },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const created = await createAdminInvite({ kind: 'signup', label: 'x', ttlHours: 24 })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/admin/invites')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ kind: 'signup', label: 'x', ttlHours: 24 })
    expect(created.token).toBe('inv_once')
    expect(created.invite.id).toBe('i9')
  })

  it('pauseAdminUser：POST /admin/users/{id}/pause', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'u3', status: 'paused' }))
    vi.stubGlobal('fetch', fetchMock)
    await pauseAdminUser('u3')
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/admin/users/u3/pause')
    expect(init.method).toBe('POST')
  })

  it('resetAdminUserPassword：返回一次性 recoveryToken', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ id: 'u3', recoveryToken: 'inv_rec', invite: { id: 'i10', kind: 'recovery' } }),
      ),
    )
    const result = await resetAdminUserPassword('u3')
    expect(result.recoveryToken).toBe('inv_rec')
    expect(result.invite.kind).toBe('recovery')
  })

  it('registerFreshRssPool：POST，apiPassword 只提交不回读；publicUrl 空则不上送', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    await registerFreshRssPool({
      freshrssUsername: 'frss-a',
      freshrssBaseUrl: 'https://freshrss.example.com',
      apiPassword: SYNTHETIC_POOL_SECRET,
    })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/admin/pool')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      freshrssUsername: 'frss-a',
      freshrssBaseUrl: 'https://freshrss.example.com',
      apiPassword: SYNTHETIC_POOL_SECRET,
    })
  })
})

describe('邀请方案与漏斗（N001/N004）请求形状与归一', () => {
  it('createInviteScheme：POST /admin/invite-schemes，body 含名称/TTL/源/预约/备注', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: 's1',
        name: '新人套餐',
        ttlHours: 48,
        initialSourceUrls: ['https://a.example/feed.xml'],
        freshrssPoolHold: true,
        quotaNote: '每人 3 源',
        createdAt: NOW_S,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const scheme = await createInviteScheme({
      name: '新人套餐',
      ttlHours: 48,
      initialSourceUrls: ['https://a.example/feed.xml'],
      freshrssPoolHold: true,
      quotaNote: '每人 3 源',
    })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/admin/invite-schemes')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      name: '新人套餐',
      ttlHours: 48,
      initialSourceUrls: ['https://a.example/feed.xml'],
      freshrssPoolHold: true,
      quotaNote: '每人 3 源',
    })
    expect(scheme).toEqual({
      id: 's1',
      name: '新人套餐',
      ttlHours: 48,
      initialSourceUrls: ['https://a.example/feed.xml'],
      freshrssPoolHold: true,
      quotaNote: '每人 3 源',
      createdAt: new Date(NOW_S * 1000).toISOString(),
    })
  })

  it('generateInvitesFromScheme：POST 每方案生成端点，返回逐条一次性 token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        scheme: { id: 's1', name: '新人套餐', ttl_hours: 48, initial_source_urls: [], freshrss_pool_hold: 0, created_at: NOW_S },
        invites: [
          { token: 'inv_g1', invite: { id: 'ig1', kind: 'signup', scheme_id: 's1', created_at: NOW_S } },
          { token: 'inv_g2', invite: { id: 'ig2', kind: 'signup', scheme_id: 's1', created_at: NOW_S } },
        ],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const batch = await generateInvitesFromScheme('s1', { count: 2 })
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/admin/invite-schemes/s1/generate-invites')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ count: 2 })
    expect(batch.invites.map((item) => item.token)).toEqual(['inv_g1', 'inv_g2'])
    expect(batch.invites[0]!.invite.schemeId).toBe('s1')
  })

  it('getInviteFunnel：totals/byScheme 归一；带 scheme_id 查询参数；无邀请码', async () => {
    const payload = () =>
      jsonResponse({
        totals: { generated: 5, pending: 2, activated: 1, expired: 1, revoked: 1, failedActivation: 3 },
        byScheme: [
          { schemeId: 's1', schemeName: '新人套餐', generated: 2, pending: 1, activated: 1, expired: 0, revoked: 0 },
          { schemeId: null, schemeName: null, generated: 3, pending: 1, activated: 0, expired: 1, revoked: 1 },
        ],
      })
    const fetchMock = vi.fn().mockImplementation(payload)
    vi.stubGlobal('fetch', fetchMock)
    const funnel = await getInviteFunnel(undefined, 's1')
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/admin/invite-funnel?scheme_id=s1')
    expect(funnel.totals).toEqual({ generated: 5, pending: 2, activated: 1, expired: 1, revoked: 1, failedActivation: 3 })
    expect(funnel.byScheme[1]).toEqual({
      schemeId: null,
      schemeName: null,
      generated: 3,
      pending: 1,
      activated: 0,
      expired: 1,
      revoked: 1,
    })
    const all = await getInviteFunnel()
    expect(fetchMock.mock.calls[1]![0]).toBe('/api/v1/admin/invite-funnel')
    expect(all.byScheme).toHaveLength(2)
  })

  it('getActivationPreview：notBefore/serverTime 归一（N002 等待生效）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ valid: false, freshrssReady: false, notBefore: '2100-01-01T00:00:00+00:00', serverTime: '2026-01-01T00:00:00+00:00' }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const preview = await getActivationPreview('inv_x')
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/auth/activation-preview?token=inv_x')
    expect(preview).toEqual({
      valid: false,
      kind: null,
      freshrssReady: false,
      notBefore: '2100-01-01T00:00:00+00:00',
      serverTime: '2026-01-01T00:00:00+00:00',
    })
  })
})

describe('权限错误', () => {
  it('非管理员 403 → ApiError(type=forbidden)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ error: { type: 'forbidden', message: 'Administrator role required.' } }, 403),
      ),
    )
    const error = await listAdminUsers().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(403)
    expect((error as ApiError).type).toBe('forbidden')
  })

  it('invite_not_active（N002）→ ApiError.extra 携带 serverTime/notBefore', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              type: 'invite_not_active',
              message: 'This invitation is not active yet.',
              serverTime: '2026-01-01T00:00:00+00:00',
              notBefore: '2100-01-01T00:00:00+00:00',
            },
          },
          403,
        ),
      ),
    )
    const error = await listAdminUsers().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).type).toBe('invite_not_active')
    expect((error as ApiError).extra).toEqual({
      serverTime: '2026-01-01T00:00:00+00:00',
      notBefore: '2100-01-01T00:00:00+00:00',
    })
  })
})
