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
import { bumpAuthEpoch } from '../store/auth'
import { useSearchState } from '../store/search-state'
import { clearBasketOnLogout } from '../store/search-basket'
import { useUndo } from '../store/undo'
import { resetAccountSettingsSync } from '../store/settings-sync'
import { clearAllDrafts } from './draft-store'
import { clearSearchHistoryOnLogout } from './search-history'
import { clearRecentReads } from './recent-reads'
import { clearReadingPositions } from './reading-position'
import { resetAnnotationsForAccountSwitch } from './annotations'
import { clearRecap } from './session-recap'
import { clearReadingPath } from './reading-path'
import { clearAllSourceAliases } from './source-aliases'
import { clearExcludedAnnotations } from './search-timeline-exclusions'
import { clearAllSpeechBookmarks } from './speech-bookmarks'
import { clearWorkspaceTabFootprints } from './workspace-tabs'
import { clearAttachmentQueue } from './attachment-queue'
import { clearEnclosurePositions } from './enclosure'
import { clearStashedSearchHits } from './search-hit-locate'

/** 登录/登出后的统一状态重置。queryClient 由调用方传入（main.tsx /
 * useQueryClient 持有同一实例）。
 *
 * FIX-069：默认广播 auth epoch（storage 事件送达其他标签页，让挂着
 * 旧身份应用子树的标签页同步重置）。跨标签页事件处理器自身调用时传
 * { broadcast: false }——否则 A↔B 标签页互相触发、乒乓循环。 */
export function resetAccountState(
  queryClient: QueryClient,
  options: { broadcast?: boolean } = {},
): void {
  const broadcast = options.broadcast ?? true
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
  // N147：暂存篮是账号内容足迹（A 勾选的引用不能出现在 B 的篮里）。
  clearBasketOnLogout()

  // 4. 本机敏感足迹（localStorage 键由各模块自持）
  clearAllDrafts() // lumirss-draft-*
  clearSearchHistoryOnLogout() // lumirss-search-history (+暂停标记)
  clearRecentReads() // lumirss-recent-reads
  clearReadingPositions() // lumirss-reading-positions

  // 4b. FIX-062：审计补齐的按账号积累足迹——批注离线缓存（含服务端
  //     同步标记复位）、阅读会话回顾、阅读路径、来源别名离线缓存、
  //     时间线排除批注、朗读书签、工作区足迹（最近关闭/预览草稿/
  //     分组折叠）、附件下载队列元数据、播放续播位置、搜索命中定位
  //     暂存（sessionStorage 同样在同一标签页内跨账号存活）。
  resetAnnotationsForAccountSwitch()
  clearRecap()
  clearReadingPath()
  clearAllSourceAliases()
  clearExcludedAnnotations()
  clearAllSpeechBookmarks()
  clearWorkspaceTabFootprints()
  clearAttachmentQueue()
  clearEnclosurePositions()
  clearStashedSearchHits()

  // 5. portable 设置的账号投影（FIX-061）：A 的未落库 dirty 键、A 的
  //    服务端 revision、hydration 完成标记与 A 的 portable 值全部归零
  //    ——B 登录翻转时重新 hydration 拿 B 自己的文档，B 的第一次设置
  //    变更绝不把 A 的整包快照 PATCH 进 B 的账号。
  resetAccountSettingsSync()

  // 6. FIX-069：广播身份变迁（登录/登出/激活/注册都走本函数）。事件
  //    只送达其他标签页；跨标签页处理器自身重置时以 broadcast:false
  //    跳过本步，避免标签页间乒乓循环。
  if (broadcast) bumpAuthEpoch()
}
