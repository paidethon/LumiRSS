/** list-organize — NEW-354 移动批量整理模式（纯逻辑）。
 *
 * 通过**明确的选择模式**整理多篇文章：进入即显示范围（视图 + 信息源
 * 范围 + 本页已加载量），统一操作栏收口全部动作；退出不遗留任何选择
 * 状态（清空 selection / 批量失败清单——与既有 exitSelectMode 同一语义，
 * 本模块只提供范围文案与边界判定的纯函数，供面板与测试同源）。
 *
 * 范围文案的标签与 lib/navigation.scopeTitle / lib/read-later 的视图
 * 语义一致——不复制数据，只做展示层组装。 */

import type { UiView } from './read-later'

/** 视图标签（与 UiView 全集一一对应）。 */
export const ORGANIZE_VIEW_LABELS: Record<UiView, string> = {
  all: '全部文章',
  unread: '未读',
  starred: '收藏',
  'read-later': '稍后读',
}

export interface OrganizeScopeInput {
  view: UiView
  /** 信息源范围标题（调用方用 scopeTitle(scope) + 订阅源标题补全）。 */
  scopeLabel: string
  /** 本页已加载条目数（批量动作绝不作用于未加载集合的诚实口径）。 */
  loadedCount: number
  selectedCount: number
}

/** 范围行文案（「范围：…」一行）。 */
export function organizeScopeLine(input: OrganizeScopeInput): string {
  const viewLabel = ORGANIZE_VIEW_LABELS[input.view] ?? input.view
  return `视图：${viewLabel} · 范围：${input.scopeLabel}`
}

/** 计数行文案（含批量上限诚实标注）。 */
export function organizeCountLine(
  input: OrganizeScopeInput,
  batchLimit: number,
): string {
  const base = `本页已加载 ${input.loadedCount} 篇 · 已选 ${input.selectedCount} 条`
  return input.selectedCount > batchLimit ? `${base}（超过一次可处理上限 ${batchLimit}）` : base
}

/** 退出整理必须清除的状态清单（面板提示 + 测试同源——「退出后不遗留
 * 选择状态」的机器可读口径）。 */
export const ORGANIZE_EXIT_CLEARS = ['selection', 'batch-failures', 'running-flag'] as const

/** 进入条件：列表页（home）且有已加载条目——空列表进入无意义，诚实禁用。 */
export function canEnterOrganizeMode(section: string, loadedCount: number): boolean {
  return section === 'home' && loadedCount > 0
}
