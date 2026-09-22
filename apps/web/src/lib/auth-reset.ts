/** auth-reset — O157 换账号防串号的单一清理入口。
 *
 * 登录成功与登出（主动/所有设备）都必须走同一个函数：把上一个账号
 * 留在客户端的「用户内容足迹」全部清掉，下一个账号绝不看到 A 的
 * 数据。原则：
 * - 清：TanStack Query 缓存（服务端数据投影）、UI 选择状态、本机
 *   草稿、搜索历史、最近阅读、阅读位置、待同步的 portable 设置
 *   dirty 键（A 未落库的设置意图不能变成对 B 的 PATCH）；
 * - 留：主题、语言、阅读排版等设备偏好（lumirss-settings 的设备
 *   本地键）——换设备/换账号不该重置无账号语义的外观偏好。
 *
 * 服务端会话本身由 Cookie 承载，登出端点负责撤销；本模块只负责
 * 客户端状态，幂等（重复调用无副作用）。
 */

import type { QueryClient } from '@tanstack/react-query'
import { useReaderUi, ALL_SCOPE } from '../store/reader-ui'
import { useSearchState } from '../store/search-state'
import { useUndo } from '../store/undo'
import { clearPendingSettingsSync } from '../store/settings-sync'
import { clearAllDrafts } from './draft-store'
import { clearSearchHistoryOnLogout } from './search-history'
import { clearRecentReads } from './recent-reads'
import { clearReadingPositions } from './reading-position'

/** 登录/登出后的统一状态重置。queryClient 由调用方传入（main.tsx /
 * useQueryClient 持有同一实例）。 */
export function resetAccountState(queryClient: QueryClient): void {
  // 1. 服务端数据缓存：文章/订阅/收藏等投影全部作废（含内存外的
  //    Query persistence，若未来接入）。clear 内部已移除全部查询与
  //    mutation 缓存并通知订阅者。
  queryClient.clear()

  // 2. UI 选择状态（reader-ui 无持久化，重置回启动默认）
  useReaderUi.setState({
    section: 'home',
    scope: ALL_SCOPE,
    view: 'all',
    selectedEntryRef: null,
    mobileSidebarOpen: false,
  })

  // 3. 会话级搜索状态 / 撤销槽（撤销动作闭包可能引用 A 的数据）
  useSearchState.getState().clear()
  useUndo.getState().clear()

  // 4. 本机敏感足迹（localStorage 键由各模块自持）
  clearAllDrafts() // lumirss-draft-*
  clearSearchHistoryOnLogout() // lumirss-search-history (+暂停标记)
  clearRecentReads() // lumirss-recent-reads
  clearReadingPositions() // lumirss-reading-positions

  // 5. portable 设置的未落库 dirty 键：A 的本地待发变更不能在 B 的
  //    会话里 PATCH 上去（下次改动会以干净 base 重新入队）。
  clearPendingSettingsSync()
}
