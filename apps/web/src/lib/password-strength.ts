/** password-strength — F016 本地密码强度估计（纯函数，无网络请求）。
 *
 * 只看两个信号：长度 × 字符类别多样性（小写 / 大写 / 数字 / 其他符号
 * 四类）。这不是安全评分，只是注册时的即时可用性反馈；真正的权威
 * 校验（最小长度等）永远在服务端。 */
export type PasswordStrength = 'weak' | 'medium' | 'strong'

export const STRENGTH_TEXT: Record<PasswordStrength, string> = {
  weak: '密码强度：弱 —— 建议加长到 12 位以上，并混用大小写字母、数字或符号。',
  medium: '密码强度：中 —— 再加长或增加字符种类会更安全。',
  strong: '密码强度：强。',
}

/** 空串返回 null（不显示提示）。 */
export function passwordStrength(value: string): PasswordStrength | null {
  if (value === '') return null
  const classes = [
    /[a-z]/,
    /[A-Z]/,
    /[0-9]/,
    /[^a-zA-Z0-9]/,
  ].filter((pattern) => pattern.test(value)).length
  if (value.length < 8) return 'weak'
  if (classes >= 3 && value.length >= 12) return 'strong'
  if (classes >= 2 && value.length >= 10) return 'strong'
  if (classes >= 2) return 'medium'
  // 单一字符类别：长度换不回多样性，最多给「中」。
  return value.length >= 16 ? 'medium' : 'weak'
}
