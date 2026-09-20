/** custom-css — F112 自定义 CSS 的安全护栏（device-local）。
 *
 * - 拦截逃逸面：@import 一律拒绝；url() 只允许相对路径与 # 片段
 *   （http/https/协议相对/绝对路径一律拒绝）——自定义 CSS 不应成为
 *   外链载体或跟踪入口；
 * - 上一有效版本备份（localStorage `lumirss-custom-css-last-valid`）：
 *   每次成功保存前把「当前生效值」存入备份键，出问题可一键恢复；
 * - 解析校验复用 reader-style.prefixCustomCss（选择器自动加
 *   .lumi-reader 前缀；花括号不配对/空选择器 → null）。 */

import { prefixCustomCss } from './reader-style'

export const CUSTOM_CSS_BACKUP_KEY = 'lumirss-custom-css-last-valid'

export interface CssCheckResult {
  ok: boolean
  reason: string | null
}

/** 拦截检查：@import / 绝对 url()。白名单 = 相对路径与 # 片段。 */
export function checkCssSafety(css: string): CssCheckResult {
  if (/@import\b/i.test(css)) {
    return { ok: false, reason: '不允许 @import（自定义 CSS 不引入外部资源）。' }
  }
  // url(...)：捕获引号内外的值；拒绝 http(s):、协议相对 //、根相对之外
  // 的绝对路径（/abs 允许吗？不——白名单仅「相对路径」与「#片段」，
  // 以 / 开头的站内绝对路径也拒绝，保持白名单最小）。
  const urlPattern = /url\(\s*(['"]?)(.*?)\1\s*\)/gi
  let match: RegExpExecArray | null
  while ((match = urlPattern.exec(css)) !== null) {
    const value = (match[2] ?? '').trim()
    if (value === '') continue
    const allowed = !/^(?:[a-z][a-z0-9+.-]*:|\/\/|\/)/i.test(value)
    if (!allowed) {
      return {
        ok: false,
        reason: `url("${value}") 不是相对路径或 # 片段——已拦截（白名单仅相对/#）。`,
      }
    }
  }
  return { ok: true, reason: null }
}

/** 保存前的完整校验：安全拦截 + 解析（前缀化）校验。返回错误文案。 */
export function validateCustomCss(css: string): string | null {
  const safety = checkCssSafety(css)
  if (!safety.ok) return safety.reason
  if (css.trim() !== '' && prefixCustomCss(css) === null) {
    return '无法解析这段 CSS（花括号不配对或空选择器）——请修正后重试'
  }
  return null
}

/** 成功保存前备份「当前生效值」（device-local，不进同步设置）。 */
export function backupCurrentCustomCss(effective: string): void {
  try {
    localStorage.setItem(CUSTOM_CSS_BACKUP_KEY, effective)
  } catch {
    /* 存储满/隐私模式：备份尽力而为 */
  }
}

/** 恢复上一有效版本；没有备份或备份与当前一致 → null。 */
export function loadBackupCustomCss(current: string): string | null {
  try {
    const backup = localStorage.getItem(CUSTOM_CSS_BACKUP_KEY)
    if (backup === null || backup === current) return null
    return backup
  } catch {
    return null
  }
}
