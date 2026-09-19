/** P1.3（2026-09 移动端专项）：列表滚动锚点（会话内存）。
 *
 * 返回链恢复 section/scope/view 后，列表还应回到原滚动位置（打开文章
 * → 返回列表锚点）。按 view|scope|section 键保存滚动容器的
 * scrollTop；恢复时内容可能尚未加载完 → 由调用方在数据到达后再试
 * （retryRestore 最多等待 limitMs）。
 *
 * 会话语义：不持久化；Reader 正文位置另由 reading-position 负责。 */

const anchors = new Map<string, number>()

export function listAnchorKey(parts: {
  section: string
  view: string
  scope: string
}): string {
  return `${parts.section}|${parts.view}|${parts.scope}`
}

export function saveListAnchor(key: string, scrollTop: number): void {
  anchors.set(key, scrollTop)
}

export function loadListAnchor(key: string): number | null {
  return anchors.get(key) ?? null
}

/** 供测试重置。 */
export function resetListAnchorsForTests(): void {
  anchors.clear()
}
