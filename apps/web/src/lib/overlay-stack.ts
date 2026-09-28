/** FIX-103 — 跨浮层栈：Escape 只作用于最上层浮层。
 *
 * 背景：Base UI 的 Escape 顶层判定（useDialogRoot 的 `escapeKey: isTopmost`）
 * 只统计 **React 树内嵌套** 的 dialog/drawer（onNestedDialogOpen 回调链）。
 * 两种真实嵌套不在其中：
 *   1. 兄弟挂载的 Base UI 浮层（如 App 层独立挂载的确认 Dialog 叠在
 *      设置 Modal 上）——双方各自的 isTopmost 都为真，一次 Escape 会
 *      同时关闭两层；
 *   2. 自绘浮层（RecentReads / CommandPalette：fixed div + 自持 Escape
 *      监听，不走 Base UI）叠在抽屉/对话框上——Base UI 不知道它们存在。
 *
 * 本模块是极简顺序栈：每个浮层 open 时 acquire（后开者在上），close 时
 * release。Base UI 原语在 onOpenChange 收到 `escape-key` 时用
 * isTopmostOverlay 门控；自绘浮层在 window **capture** 阶段处理 Escape
 * （capture 先于 Base UI 的 document bubble 监听），仅在最上层时关闭并
 * stopPropagation——下层（无论 Base UI 还是自绘）都收不到这次按键。
 *
 * 只管「Escape 关谁」这一件事；滚动锁/焦点/返回链仍归 Base UI 与
 * nav-history 各自所有。 */

const stack: string[] = []

/** 浮层打开：登记并置于栈顶；返回 release 函数（重复 acquire 幂等——
 * StrictMode mount→cleanup→remount 后仍在栈顶）。 */
export function acquireTopmostOverlay(id: string): () => void {
  const existing = stack.indexOf(id)
  if (existing !== -1) stack.splice(existing, 1)
  stack.push(id)
  return () => {
    const index = stack.indexOf(id)
    if (index !== -1) stack.splice(index, 1)
  }
}

/** 该浮层是否是当前最上层（未登记的 id 恒为 false）。 */
export function isTopmostOverlay(id: string): boolean {
  return stack[stack.length - 1] === id
}

/** 测试辅助：清空栈（避免用例间串扰）。 */
export function resetOverlayStackForTests(): void {
  stack.length = 0
}
