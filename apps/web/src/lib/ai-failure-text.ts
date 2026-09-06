import { ApiError } from '../api/client'

/**
 * AI 错误类型 → 稳定用户文案（summary / translation / conversation 共用）。
 *
 * BFF 错误信封类型带 ai_ 前缀（ai_timeout），缓存 failureType 不带
 * （timeout）——两种都按同一稳定文案查找。
 */
const FAILURE_TEXT: Record<string, string> = {
  auth_error: 'API 密钥被服务端拒绝，请检查服务端的 AI_API_KEY 配置。',
  model_error: '模型或接口地址不存在，请检查 AI 设置中的 Base URL 与 Model。',
  rate_limited: 'AI 服务请求过于频繁，请稍后再试。',
  timeout: 'AI 服务响应超时，请重试。',
  invalid_response: 'AI 服务返回了无法解析的结果，请重试。',
  upstream_error: 'AI 服务暂时不可用，请稍后再试。',
  not_configured:
    'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
  ai_not_configured:
    'AI 未配置。请在右上角「设置 → AI」中填写 Base URL 与 Model，并在服务端配置 API 密钥。',
}

/** 各 AI 功能自己的少量特色文案（动词条目 + 兜底）。 */
export interface AiFailureWording {
  /** error 不是 ApiError 时的兜底（生成失败 / 翻译失败 / 发送失败）。 */
  fallback: string
  /** interrupted（上次生成/翻译被中断）。 */
  interrupted: string
  /** 文章没有可处理的正文（没有可摘要/翻译的正文内容）。 */
  contentUnavailable: string
}

function lookup(type: string, wording: AiFailureWording): string | undefined {
  const text: Record<string, string> = {
    ...FAILURE_TEXT,
    interrupted: wording.interrupted,
    content_unavailable: wording.contentUnavailable,
    ai_content_unavailable: wording.contentUnavailable,
  }
  return text[type] ?? text[type.replace(/^ai_/, '')]
}

/** 按缓存 failureType 查文案；未知类型返回 fallback。 */
export function aiFailureTypeText(
  type: string,
  wording: AiFailureWording,
): string {
  return lookup(type, wording) ?? wording.fallback
}

/** 按 unknown error（通常是 ApiError）查文案；兜底 error.message 或 fallback。 */
export function aiFailureText(error: unknown, wording: AiFailureWording): string {
  if (error instanceof ApiError) {
    const known = lookup(error.type, wording)
    if (known !== undefined) {
      return known
    }
  }
  return error instanceof Error ? error.message : wording.fallback
}
