/** N034：发布时间可信度异常代码 → 可读解释（徽标 tooltip / aria-label）。
 * 代码与服务端投影 time_flags 的稳定代码一致（entry_intake.time_flag_codes）：
 * missing / no_timezone / future / too_old。 */

const TIME_CREDIBILITY_LABELS: Record<string, string> = {
  missing: '发布时间缺失',
  no_timezone: '发布时间未标明时区',
  future: '发布时间在未来（晚于当前 1 天以上）',
  too_old: '发布时间早于 2000 年',
}

export function timeCredibilityExplanation(codes: string): string {
  return codes
    .split(',')
    .map((code) => TIME_CREDIBILITY_LABELS[code] ?? code)
    .join('；')
}
