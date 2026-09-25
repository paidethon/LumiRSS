/** password-strength — F016/N005 本地密码强度估计（纯函数，无网络请求）。
 *
 * 信号：长度 × 字符类别多样性（小写 / 大写 / 数字 / 其他符号四类）
 * + N005 惩罚项（同字符连击、连续序列）。这不是安全评分，只是注册 /
 * 改密 / 激活设密时的即时可用性反馈；真正的权威校验（最小长度等）
 * 永远在服务端。绝不发任何网络请求。 */
export type PasswordStrength = 'weak' | 'medium' | 'strong'

export const STRENGTH_TEXT: Record<PasswordStrength, string> = {
  weak: '密码强度：弱 —— 建议加长到 12 位以上，并混用大小写字母、数字或符号。',
  medium: '密码强度：中 —— 再加长或增加字符种类会更安全。',
  strong: '密码强度：强。',
}

/** 同一字符最长连击（如 aaaa → 4）。 */
function longestRepeat(value: string): number {
  let longest = 0
  let run = 1
  for (let i = 1; i < value.length; i++) {
    if (value[i] === value[i - 1]) run++
    else run = 1
    if (run > longest) longest = run
  }
  return longest
}

/** 最长连续升/降序列（如 abcd / 4321 → 4）。 */
function longestSequence(value: string): number {
  let longest = 0
  let run = 1
  for (let i = 1; i < value.length; i++) {
    const prev = value.charCodeAt(i - 1)
    const curr = value.charCodeAt(i)
    if (curr === prev + 1 || curr === prev - 1) run++
    else run = 1
    if (run > longest) longest = run
  }
  return longest
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
  // N005 惩罚：长连击/长序列把「强」拉回「中」（纯本地启发式）。
  const penalized = longestRepeat(value) >= 3 || longestSequence(value) >= 4
  if (classes >= 3 && value.length >= 12 && !penalized) return 'strong'
  if (classes >= 2 && value.length >= 10 && !penalized) return 'strong'
  if (classes >= 2) return 'medium'
  // 单一字符类别：长度换不回多样性，最多给「中」。
  return value.length >= 16 ? 'medium' : 'weak'
}
