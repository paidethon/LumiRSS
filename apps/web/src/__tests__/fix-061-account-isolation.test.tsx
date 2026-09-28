/** FIX-061 — 换账号（A 登出 → B 登录）后的账户隔离。
 *
 * 两个互补的防线，都走真实登录/登出路径（resetAccountState + auth 门
 * 翻转），不直接调用内部函数伪造状态：
 *
 * 1. 查询缓存：A 的 feeds 缓存不能在 B 会话里复活 —— 同一挂载中的
 *    useQuery 必须重新请求并渲染 B 的数据；
 * 2. portable 设置：settings-sync 的 hydration 状态（hydratedOk /
 *    serverRevision）必须在换账号时归零 —— 否则 B 的整个会话运行在
 *    A 的 portable 设置上，B 的第一次设置变更会把 A 的整包快照
 *    PATCH 进 B 的服务端文档（真实跨账号写入）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { useAuthStore, type AuthIdentity } from '../store/auth'
import { useAppSettings } from '../store/app-settings'
import {
  flushSettingsSyncForTests,
  initSettingsSync,
  resetSettingsSyncForTests,
} from '../store/settings-sync'
import { resetAccountState } from '../lib/auth-reset'

// ---- 服务端内存态：按当前登录用户返回不同 settings 文档（模拟 BFF） ----

interface ServerDoc {
  stored: boolean
  revision: number
  values: Record<string, string | number | boolean>
}

const DOCS: Record<'a' | 'b', ServerDoc> = {
  a: { stored: true, revision: 7, values: { readerFontSize: 25, accentColor: '#aa11bb' } },
  b: { stored: true, revision: 3, values: { readerFontSize: 21, accentColor: '#009876' } },
}

let currentUser: 'a' | 'b' = 'a'
const patchCalls: Record<string, string | number | boolean>[] = []

function stubSettingsFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = String(url)
      if (path === '/api/v1/settings') {
        const method = init?.method ?? 'GET'
        const doc = DOCS[currentUser]
        if (method === 'GET') {
          return new Response(
            JSON.stringify({ schemaVersion: 1, stored: doc.stored, revision: doc.revision, ...doc.values }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }
        if (method === 'PATCH') {
          const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, string | number | boolean>
          patchCalls.push(body)
          doc.revision += 1
          doc.stored = true
          doc.values = { ...doc.values, ...body }
          return new Response(
            JSON.stringify({ schemaVersion: 1, stored: true, revision: doc.revision, ...doc.values }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }
      }
      return new Response(JSON.stringify({ error: { type: 'not_found', message: path } }), { status: 404 })
    }),
  )
}

const identityA: AuthIdentity = { userId: 'user-a', username: 'alice', role: 'owner' }
const identityB: AuthIdentity = { userId: 'user-b', username: 'bob', role: 'member' }

beforeEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  resetSettingsSyncForTests()
  currentUser = 'a'
  patchCalls.length = 0
  useAppSettings.getState().reset()
  useAuthStore.setState({ status: 'authenticated', mode: 'session', identity: identityA })
  stubSettingsFetch()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetSettingsSyncForTests()
})

describe('FIX-061 portable 设置换账号隔离', () => {
  it('A 登出 → B 登录：B 重新 hydration，A 的 portable 值与 baseRevision 不泄漏进 B 的会话', async () => {
    // ---- A 会话：hydration 拿到 A 的文档，并产生一次带 revision 的 PATCH ----
    initSettingsSync({ debounceMs: 0 })
    await waitFor(() => expect(useAppSettings.getState().settings.readerFontSize).toBe(25))
    expect(useAppSettings.getState().settings.accentColor).toBe('#aa11bb')

    useAppSettings.getState().update({ accentColor: '#223344' })
    await flushSettingsSyncForTests()
    await waitFor(() => expect(DOCS.a.revision).toBe(8))

    // ---- A 登出：真实清理路径（AccountMenu 的统一出口） ----
    useAuthStore.getState().setStatus('unauthenticated')
    resetAccountState(new QueryClient())

    // A 的 portable 投影不留在内存/本地存储里（B 登录前的窗口期也不可见）
    expect(useAppSettings.getState().settings.readerFontSize).toBe(17)
    expect(useAppSettings.getState().settings.accentColor).toBe('#6d78e8')

    // ---- B 登录：服务端切换为 B 的文档，auth 门翻回 authenticated ----
    currentUser = 'b'
    useAuthStore.getState().setIdentity(identityB)
    useAuthStore.getState().setStatus('authenticated')

    // B 的文档必须重新 hydration 覆盖本地（而不是沿用 A 的值跑完整个会话）
    await waitFor(() => {
      expect(useAppSettings.getState().settings.readerFontSize).toBe(21)
      expect(useAppSettings.getState().settings.accentColor).toBe('#009876')
    })

    // B 的第一次设置变更：PATCH 必须带 B 的 baseRevision，且整包快照里
    // 不得出现 A 的值（readerFontSize 25 是 A 的排版，不能写进 B 的账号）
    useAppSettings.getState().update({ accentColor: '#445566' })
    await flushSettingsSyncForTests()
    await waitFor(() => expect(patchCalls.length).toBeGreaterThan(1))
    const lastPatch = patchCalls[patchCalls.length - 1]
    expect(lastPatch.baseRevision).toBe(3)
    expect(lastPatch.readerFontSize).toBe(21)
    expect(lastPatch.accentColor).toBe('#445566')
  })
})

// ---- 查询缓存隔离（真实 AuthGate 语义：登出翻门卸载 App，B 登录重挂载） ----

function FeedProbe(): React.ReactElement {
  const { data } = useQuery({
    queryKey: ['feeds'],
    queryFn: async ({ signal }) => {
      const response = await fetch('/api/v1/feeds', { signal })
      if (!response.ok) throw new Error('feeds failed')
      return (await response.json()) as { title: string }
    },
  })
  return <p>{data === undefined ? 'loading' : data.title}</p>
}

/** main.tsx AuthGate 的最小复刻：unauthenticated 时不渲染应用子树
 * （真实应用正是靠这一点保证换账号后没有任何挂载中的旧查询观察者）。 */
function Gate(): React.ReactElement {
  const status = useAuthStore((s) => s.status)
  if (status !== 'authenticated') return <p role="status">登录入口</p>
  return <FeedProbe />
}

describe('FIX-061 查询缓存换账号隔离', () => {
  it('A 登出翻门卸载应用 → B 登录重挂载：重新请求，B 看不到 A 的 feeds', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const fetchMock = vi.fn(async (url: unknown) => {
      if (String(url) === '/api/v1/feeds') {
        return new Response(
          JSON.stringify({ title: currentUser === 'a' ? 'A 的订阅' : 'B 的订阅' }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response(JSON.stringify({}), { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <QueryClientProvider client={queryClient}>
        <Gate />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByText('A 的订阅')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // 换账号：缓存随 resetAccountState 作废 + 门翻到登录页（子树卸载）。
    useAuthStore.getState().setStatus('unauthenticated')
    resetAccountState(queryClient)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('登录入口'))
    expect(queryClient.getQueryData(['feeds'])).toBeUndefined()

    // B 登录：重新挂载 → 重新请求 → 只有 B 的数据。
    currentUser = 'b'
    useAuthStore.getState().setIdentity(identityB)
    useAuthStore.getState().setStatus('authenticated')
    await waitFor(() => expect(screen.getByText('B 的订阅')).toBeInTheDocument())
    expect(queryClient.getQueryData<{ title: string }>(['feeds'])?.title).toBe('B 的订阅')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.queryByText('A 的订阅')).not.toBeInTheDocument()
  })
})
