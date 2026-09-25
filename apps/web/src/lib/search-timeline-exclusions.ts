/** search-timeline-exclusions — N149 时间线批注的手动排除（设备本地）。
 *
 * - 排除列表只存在本设备 localStorage（绝不上传）；
 * - 上限 200 条，超出时丢弃最老（诚实有界）；
 * - 变更后由面板触发时间线 refetch，重渲后排除即生效。 */

const STORAGE_KEY = 'lumirss-timeline-excluded-annotations'
const MAX_EXCLUDED = 200

export function readExcludedAnnotationIds(): string[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string')
  } catch {
    return []
  }
}

function writeExcluded(ids: string[]): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(-MAX_EXCLUDED)))
  } catch {
    /* 写失败不影响本会话 */
  }
}

/** 排除一条批注（幂等）；返回最新列表。 */
export function excludeAnnotation(id: string): string[] {
  const current = readExcludedAnnotationIds()
  if (!current.includes(id)) current.push(id)
  writeExcluded(current)
  return readExcludedAnnotationIds()
}

/** 撤销全部排除。 */
export function clearExcludedAnnotations(): void {
  writeExcluded([])
}

export function isAnnotationExcluded(excluded: string[], id: string): boolean {
  return excluded.includes(id)
}
