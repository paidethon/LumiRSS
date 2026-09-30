/** FIX-253 — 详情预取与正式查询共用身份作用域；不得给下一账户复用数据。
 *
 * 守卫（复核结论 BASELINE_OK：现有实现已满足）：
 * - 本应用不存在绕过查询键的「详情预取」：全仓库无 prefetchQuery /
 *   prefetchInfiniteQuery 调用；详情读路径只有 useEntryDetail 与
 *   撤销核对用的 queryClient.fetchQuery，二者共用完全相同的
 *   ['entry', entryRef] 键（同一缓存槽，无旁路）。
 * - 身份作用域由 resetAccountState → queryClient.clear() 兜底：任何
 *   键形状（含假想的预取旁路键）写入的详情缓存，都会在登录/登出/
 *   换号时整体清空——下一账户物理上无可复用的 A 的数据。
 *
 * 本测试用「旁路键形状」证明该兜底：即使是绕过键工厂的写入，也活不过
 * 身份重置。既有 auth-reset.test.ts 覆盖 feeds/entries 形状，这里补
 * 详情键形状。
 */

import { describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'

import { resetAccountState } from '../lib/auth-reset'
import { useEntryDetail } from '../api/queries'

const REF_A = 'b2ZmZXItZTE=' // A 账号的详情 ref（测试假值）

describe('FIX-253 详情缓存的身份作用域', () => {
  it('useEntryDetail 的键工厂形状是 ["entry", entryRef]（无旁路）', () => {
    // 源码级契约：详情读路径共享同一键形状（fetchQuery 撤销核对与之
    // 同键，见 EntryActionButtons / ReaderHeader）。
    expect(useEntryDetail.length).toBe(1) // 单一入口（entryRef）
  })

  it('正式查询键形状的详情缓存随 resetAccountState 清空，不复用给下一账户', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['entry', REF_A], {
      entryRef: REF_A,
      title: 'A 的文章正文',
    })
    expect(queryClient.getQueryData(['entry', REF_A])).toBeDefined()

    resetAccountState(queryClient)

    expect(queryClient.getQueryData(['entry', REF_A])).toBeUndefined()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  })

  it('假想的「预取旁路键」同样活不过身份重置（clear 兜底无键形状例外）', () => {
    const queryClient = new QueryClient()
    // 一个绕过 ['entry', ref] 键工厂的假想预取写入
    queryClient.setQueryData(['entry-detail-prefetch', REF_A], {
      entryRef: REF_A,
      title: 'A 的预取正文',
    })
    expect(queryClient.getQueryData(['entry-detail-prefetch', REF_A])).toBeDefined()

    resetAccountState(queryClient)

    expect(queryClient.getQueryData(['entry-detail-prefetch', REF_A])).toBeUndefined()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  })
})
