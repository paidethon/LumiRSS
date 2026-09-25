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
    const pattern = new RegExp('^' + template.replace(/:[^/]+/g, '[^/]+') + '$')
    if (pattern.test(feedPath)) return route
  }
  return null
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

export interface KeyedTemplate {
  /** Lumi catalog 的 {key} 占位模板（如 /github/starred_repos/{user}）。 */
  pathTemplate: string
}

/**
 * N024：从 feedUrl 路径反推 {key} 模板的当前参数值（段级一一对应，
 * 与 BFF build_path 的 `[^/]+` 段语义一致）。模板与路径段数不符 →
 * null（诚实回退，不臆造参数）。
 */
export function extractTemplateParams(
  template: string,
  feedUrl: string,
): Record<string, string> | null {
  let feedPath: string
  try {
    feedPath = new URL(feedUrl).pathname
  } catch {
    return null
  }
  const normalized = template.startsWith('/') ? template : `/${template}`
  const templateSegments = normalized.split('/')
  const feedSegments = feedPath.split('/')
  if (templateSegments.length !== feedSegments.length) return null
  const params: Record<string, string> = {}
  for (let index = 0; index < templateSegments.length; index += 1) {
    const segment = templateSegments[index] ?? ''
    const placeholder = /^\{(\w+)\}$/.exec(segment)
    if (placeholder !== null) {
      params[placeholder[1] ?? ''] = decodeURIComponent(feedSegments[index] ?? '')
      continue
    }
    if (segment !== feedSegments[index]) return null
  }
  return params
}
