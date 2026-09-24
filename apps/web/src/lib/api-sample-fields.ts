/** api-sample-fields — N128 用样例预览：从粘贴的 JSON 样例推导 JMESPath。
 *
 * 纯函数、零依赖：解析样例 → 遍历「顶层 + 首个数组元素」的键 →
 * 生成 items 表达式与字段下拉候选 → 由选中的键生成 JMESPath 表达式
 * （含特殊字符的键自动用带引号标识符）。
 */

export type SampleJson = unknown

/** 解析用户粘贴的 JSON；失败返回 null（由调用方提示）。 */
export function parseSampleJson(text: string): SampleJson | null {
  try {
    return JSON.parse(text) as SampleJson
  } catch {
    return null
  }
}

/** 生成 fieldMap 五键（id/title/url/published/body）的下拉候选。 */
export interface SampleFieldOptions {
  /** items 表达式候选（如 `[*]`、`items`、`data.list`）。 */
  itemsExprs: string[]
  /** 首个 items 候选下，每个数组元素可见的字段键（扁平，一层）。 */
  fieldKeys: string[]
}

const MAX_KEYS = 64

function collectKeys(objects: unknown[]): string[] {
  const keys: string[] = []
  const seen = new Set<string>()
  for (const obj of objects) {
    if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) continue
    for (const key of Object.keys(obj as Record<string, unknown>)) {
      if (!seen.has(key)) {
        seen.add(key)
        keys.push(key)
        if (keys.length >= MAX_KEYS) return keys
      }
    }
  }
  return keys
}

/** 遍历样例结构：顶层键 + （每个数组值/根数组的）首个元素键。 */
export function sampleFieldOptions(sample: SampleJson): SampleFieldOptions {
  const itemsExprs: string[] = []
  let fieldKeys: string[] = []

  if (Array.isArray(sample)) {
    itemsExprs.push('[*]')
    fieldKeys = collectKeys(sample.slice(0, 10))
  } else if (sample !== null && typeof sample === 'object') {
    const record = sample as Record<string, unknown>
    // 顶层键也可以直接是字段（根即单条内容的场景）。
    fieldKeys = Object.keys(record).slice(0, MAX_KEYS)
    // 数组值的键 → items 候选（data.list / items …）。
    let firstArraySeen = false
    for (const [key, value] of Object.entries(record)) {
      if (Array.isArray(value) && value.length > 0) {
        itemsExprs.push(key)
        if (!firstArraySeen) {
          // 第一个命中的数组键的元素键并入字段候选（向导默认值）。
          firstArraySeen = true
          const elementKeys = collectKeys(value.slice(0, 10))
          fieldKeys = Array.from(new Set([...fieldKeys, ...elementKeys])).slice(0, MAX_KEYS)
        }
      }
    }
  }
  return { itemsExprs, fieldKeys }
}

/** JMESPath 标识符：字母/数字/下划线开头且全为安全字符 → 裸标识符；
 * 其余（连字符、点、中文、空格…）→ 带引号标识符。 */
export function toFieldExpr(key: string): string {
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) return key
  return JSON.stringify(key)
}
