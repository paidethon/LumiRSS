/** 管理台 API client 契约测试 — 0067。
 *
 * 走真实 client（不 vi.mock），fetch stub 按路径应答。覆盖：
 * - BFF 的 snake_case / epoch 秒形状 → Web DTO 归一（AdminUser /
 *   AdminInvite / FreshRssPoolStatus）；
 * - 请求形状（createAdminInvite / registerFreshRssPool 的 body、
 *   危险操作的 method/路径）；
 * - 403 → ApiError（type=forbidden）。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  createAdminInvite,
  getFreshRssPool,
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
      createdAt: new Date((NOW_S - 60) * 1000).toISOString(),
    })
    // 未知 role 收敛为 member、缺失时间戳 → null（诚实缺省）
    expect(users[1]!.role).toBe('member')
    expect(users[1]!.createdAt).toBeNull()
    expect(users[1]!.displayName).toBeNull()
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/admin/users')
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
})
