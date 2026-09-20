/** draft-store 内部只读视图（避免 version-check 直接依赖整个 draft-store
 * 的公开 API 形状；列出现存草稿键供「有未保存草稿」判定）。 */

export function listDraftKeysOf(): string[] {
  try {
    if (typeof localStorage === 'undefined') return []
    const keys: string[] = []
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i)
      if (key !== null && key.startsWith('lumirss-draft-')) keys.push(key)
    }
    return keys
  } catch {
    return []
  }
}
