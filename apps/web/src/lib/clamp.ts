/** 取整并夹取到 [min, max]（pane 宽度、reader 数值档位共用）。 */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)))
}
