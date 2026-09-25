/** F047 RSSHub 参数编辑工具 —— 路由匹配与脱敏。 */

export const SENSITIVE_QUERY = /token|key|secret|sign|code|password/i

/** query 中 token/key 类参数值显示 ***（路径与其它参数原样）。 */
export function maskQuery(url: string): string {
  try {
    const parts = new URL(url)
    const masked = [...parts.searchParams.entries()].map(([key, value]) => [
      key,
      SENSITIVE_QUERY.test(key) ? '***' : value,
    ])
    parts.search = ''
    const base = parts.toString()
    if (masked.length === 0) return base
    return `${base}${masked.map(([k, v], i) => `${i === 0 ? '?' : '&'}${k}=${v}`).join('')}`
  } catch {
    return url
  }
}

export interface RouteLike {
  pathTemplate: string
}

/** pathTemplate 占位符段 → 通配（`{name}` 为 Lumi 目录格式；`:name`
 * 仅为兼容旧数据保留）。 */
const PLACEHOLDER_SEGMENT = /\{([^/}]+)\}|:([^/]+)/g

function placeholderName(segment: string): string | null {
  const brace = /^\{([^/}]+)\}$/.exec(segment)
  if (brace !== null) return brace[1]
  const colon = /^:([^/]+)$/.exec(segment)
  if (colon !== null) return colon[1]
  return null
}

/** feedUrl 路径与 pathTemplate 前缀匹配（:param 段通配）。 */
export function matchRoute<T extends RouteLike>(routes: readonly T[], feedUrl: string): T | null {
  let feedPath = ''
  try {
    feedPath = new URL(feedUrl).pathname
  } catch {
    return null
  }
  for (const route of routes) {
    const template = route.pathTemplate.startsWith('/') ? route.pathTemplate : `/${route.pathTemplate}`
    const pattern = new RegExp(
      '^' + template.replace(PLACEHOLDER_SEGMENT, '[^/]+') + '$',
    )
    if (pattern.test(feedPath)) return route
  }
  return null
}

/** N030：pathTemplate 的占位符参数名（`{user}` / `:user` → 'user'，
 * 按出现顺序）。 */
export function pathPlaceholderKeys(pathTemplate: string): string[] {
  const names: string[] = []
  for (const segment of pathTemplate.split('/')) {
    const name = placeholderName(segment)
    if (name !== null) names.push(name)
  }
  return names
}

/** N030：按模板反解 feedUrl 路径段的占位符值（段数不齐 / 字面段不符
 * → null）。值原样保留（不做解码改写），与 BFF match_route_path 的
 * 反解口径一致。 */
export function extractPathParams(pathTemplate: string, feedUrl: string): Record<string, string> | null {
  let feedPath = ''
  try {
    feedPath = new URL(feedUrl).pathname
  } catch {
    return null
  }
  const template = pathTemplate.startsWith('/') ? pathTemplate : `/${pathTemplate}`
  const templateParts = template.split('/')
  const feedParts = feedPath.split('/')
  if (templateParts.length !== feedParts.length) return null
  const params: Record<string, string> = {}
  for (let index = 0; index < templateParts.length; index += 1) {
    const name = placeholderName(templateParts[index])
    if (name !== null) {
      params[name] = feedParts[index]
      continue
    }
    if (templateParts[index] !== feedParts[index]) return null
  }
  return params
}

/** N025/N026：路由失败分类 → 中文标签（未知分类诚实回显原值）。 */
export function rsshubFailureClassLabel(failureClass: string): string {
  const known: Record<string, string> = {
    rsshub_unreachable: 'RSSHub 不可达',
    upstream_reject: '上游拒绝',
    auth_failure: '鉴权失败',
    auth_error: '鉴权错误',
    not_found: '路由不存在',
    rate_limited: '被限流',
    no_new_content: '无新内容',
    bad_content: '内容异常',
    network_error: '网络错误',
  }
  return known[failureClass] ?? failureClass
}
