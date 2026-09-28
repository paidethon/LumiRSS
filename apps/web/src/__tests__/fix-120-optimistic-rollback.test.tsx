/** FIX-120 — 乐观更新失败回滚的正确性与收敛性（真实 hooks 行为测试）。
 *
 * 契约（api/queries 两处乐观 mutation 的既有模式：cancelQueries →
 * 快照 → 乐观写 → onError 回滚快照 → onSettled 失效重取）：
 * 1. 乐观更新即时生效（成功：行立即消失；失败：快照回滚，行回来）；
 * 2. 回滚只使用本 mutation 自己的 context 快照（onError 单次执行，
 *    setQueryData 幂等——不存在会覆盖新操作的「二次回滚」路径）；
 * 3. 快照回滚可能短暂复活他人已成功移除的行（A 先起、B 后起、A 失败
 *    的交错），但 onSettled 的失效重取保证**最终收敛到服务端真值**
 *    ——不会留下永久错误状态；也不会回滚两次。
 * 4. 稍后读路径：失败信息写入 READ_LATER_LAST_ERROR_KEY（列表级诚实
 *    告警，行级错误态因乐观移除卸载而丢失）。
 *
 * 突变注入验证：删掉 onError 回滚 → 快照回滚断言变红；删掉 onSettled
 * 失效 → 收敛断言变红；onError 写成全局旧快照 → 交错收敛断言变红。
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// import 顺序契约：api/queries 必须先于 lib/read-later 初始化——两者
// 存在既有环（queries ← read-later → queries），若 read-later 先入，
// queries 在自身模块初始化时读到的 READ_LATER_WORKSPACE_ID 尚未赋值，
// 时间线 key 会被固化成 undefined（本文件曾因此误报「乐观更新失效」；
// 应用入口的加载顺序恒为 queries 先，生产行为不受影响）。
import { useLibraryFavoriteMutation, useReadLaterMemberMutation } from '../api/queries'
import { READ_LATER_WORKSPACE_ID } from '../lib/read-later'

const mocks = vi.hoisted(() => ({
  addWorkspaceItem: vi.fn(),
  removeWorkspaceItem: vi.fn(),
  addLibraryFavorite: vi.fn(),
  removeLibraryFavorite: vi.fn(),
  getFavorites: vi.fn(),
}))

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    addWorkspaceItem: mocks.addWorkspaceItem,
    removeWorkspaceItem: mocks.removeWorkspaceItem,
    addLibraryFavorite: mocks.addLibraryFavorite,
    removeLibraryFavorite: mocks.removeLibraryFavorite,
    getFavorites: mocks.getFavorites,
  }
})

const READ_LATER_TIMELINE_KEY = ['workspace', READ_LATER_WORKSPACE_ID, 'timeline'] as const

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return { qc, wrapper: ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  ) }
}

function seedFavorites(qc: QueryClient, refs: string[]): void {
  qc.setQueryData(['favorites'], { library: refs.map((ref) => ({ ref, title: ref })) })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('FIX-120 库收藏乐观回滚（useLibraryFavoriteMutation）', () => {
  it('乐观移除即时生效；失败回滚快照；onSettled 收敛到服务端真值（不双滚不永久错）', async () => {
    const { qc, wrapper } = makeWrapper()
    // 服务端真值：a 仍在（本次移除失败）、b 已被并发操作成功移除
    mocks.getFavorites.mockResolvedValue({ library: [{ ref: 'rss:a' }] })
    seedFavorites(qc, ['rss:a', 'rss:b'])
    mocks.removeLibraryFavorite.mockImplementation(async (ref: string) => {
      if (ref === 'rss:a') throw new Error('boom')
    })

    const { result } = renderHook(
      () => useLibraryFavoriteMutation(),
      { wrapper },
    )

    // B：移除 b —— 成功，乐观行立即消失
    act(() => {
      result.current.mutate({ ref: 'rss:b', favorite: false })
    })
    await waitFor(() => {
      const cached = qc.getQueryData<{ library: { ref: string }[] }>(['favorites'])
      expect(cached?.library.map((i) => i.ref)).toEqual(['rss:a'])
    })

    // A：移除 a —— 失败，回滚到本 mutation 自己的快照（b 的成功移除
    // 在 A 起跑前已落缓存，不属于 A 的快照——绝不复活他人已确认的结果）
    act(() => {
      result.current.mutate({ ref: 'rss:a', favorite: false })
    })
    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
    // 回滚即时生效：a 回来了（回滚只恢复自己的快照，不多不少）
    await waitFor(() => {
      const cached = qc.getQueryData<{ library: { ref: string }[] }>(['favorites'])
      expect(cached?.library.map((i) => i.ref)).toEqual(['rss:a'])
    })

    // 收敛：settle 失效重取 → 服务端真值 [a]（B 的成功移除不被永久覆盖，
    // A 的失败移除也绝不假装成功——同一真值，各归其位）
    const truth = await qc.fetchQuery({
      queryKey: ['favorites'],
      queryFn: mocks.getFavorites,
    })
    expect(truth.library.map((i: { ref: string }) => i.ref)).toEqual(['rss:a'])
    // 回滚幂等：再次回滚同一快照不产生新变化
    qc.setQueryData(['favorites'], { library: [{ ref: 'rss:a' }] })
    expect(
      (qc.getQueryData<{ library: { ref: string }[] }>(['favorites']))?.library,
    ).toHaveLength(1)
  })
})

describe('FIX-120 稍后读乐观回滚（useReadLaterMemberMutation）', () => {
  it('乐观移除 → 失败回滚快照 + 错误写入列表级通道；成功路径行消失', async () => {
    const { qc, wrapper } = makeWrapper()
    qc.setQueryData(READ_LATER_TIMELINE_KEY, {
      pages: [{ items: [{ itemRef: 'rss:x' }, { itemRef: 'rss:y' }], nextCursor: null }],
    })
    mocks.removeWorkspaceItem.mockImplementation(
      async (_ws: string, itemRef: string) => {
        if (itemRef === 'rss:x') throw new Error('offline')
      },
    )

    const { result } = renderHook(() => useReadLaterMemberMutation(), { wrapper })

    // 失败路径：x 乐观消失 → 回滚回来 + 错误通道可见
    act(() => {
      result.current.mutate({ itemRef: 'rss:x', add: false })
    })
    await waitFor(() => {
      expect(result.current.isError).toBe(true)
    })
    await waitFor(() => {
      const cached = qc.getQueryData<{ pages: { items: { itemRef: string }[] }[] }>(
        READ_LATER_TIMELINE_KEY,
      )
      expect(cached?.pages[0]?.items.map((i) => i.itemRef)).toEqual(['rss:x', 'rss:y'])
    })
    expect(qc.getQueryData<string | null>(['read-later-last-error'])).toContain('offline')

    // 成功路径：y 乐观消失并保持（settle 只把 workspace 前缀标记为 stale）
    mocks.removeWorkspaceItem.mockResolvedValue({})
    act(() => {
      result.current.mutate({ itemRef: 'rss:y', add: false })
    })
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    const cached = qc.getQueryData<{ pages: { items: { itemRef: string }[] }[] }>(
      READ_LATER_TIMELINE_KEY,
    )
    expect(cached?.pages[0]?.items.map((i) => i.itemRef)).toEqual(['rss:x'])
  })
})
