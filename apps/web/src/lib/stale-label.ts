/** 差异化失效状态（pool #13）：BFF resolve 现在为 stale 卡片给出
 * staleReason（unsupported / not_found / timeout / error），UI 据此
 * 区分「永久失效（建议移除）」与「暂时不可用（可重试）」，而不是一律
 * 显示同一个「源已失效」。旧服务端无该字段时回退通用文案。 */

export type StaleHint = { badge: string; hint: string; retryable: boolean }

export function staleState(reason: string | null | undefined): StaleHint {
  switch (reason) {
    case 'not_found':
      return {
        badge: '内容已删除',
        hint: '内容已不存在，建议移除。',
        retryable: false,
      }
    case 'unsupported':
      return {
        badge: '来源暂不支持',
        hint: '当前没有解析该来源的能力，可移除或等待支持。',
        retryable: false,
      }
    case 'timeout':
    case 'error':
      return {
        badge: '暂时不可用',
        hint: '源暂时不可用，稍后可重试。',
        retryable: true,
      }
    default:
      return {
        badge: '源已失效',
        hint: '源已失效，无法打开原文，建议移除。',
        retryable: false,
      }
  }
}
