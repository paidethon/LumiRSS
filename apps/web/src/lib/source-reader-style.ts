/** source-reader-style — F055 消费端：per-source 阅读样式覆盖合并。
 *
 * 服务端 source_overrides.readerStyle（fontSize/lineHeight/width 三键，
 * 数值区间由 BFF 写入时校验）只在打开匹配来源的条目时生效：
 * - 全局设置仍是基础（未覆盖的键继续走根节点 CSS 变量）；
 * - 覆盖仅限这三键，逐键生效（子集可只覆盖其一）；
 * - width 在移动端忽略（视口本来就窄，覆盖宽度无意义）。
 *
 * 纯函数：输入当前条目来源 + 服务端覆盖列表 + 设备形态，输出需要
 * 内联到正文容器上的 CSS 变量键值（null = 无任何覆盖）。 */

/** 服务端 readerStyle 三键（BFF validate_reader_style 区间：
 * fontSize 12..28、lineHeight 1.4..2.6、width 480..1600）。 */
export interface SourceReaderStyle {
  fontSize?: number
  lineHeight?: number
  width?: number
}

export interface SourceOverrideLike {
  feedUrl: string
  /** 服务端可能返回部分键（每键独立可选），null = 恢复跟随全局。 */
  readerStyle?: { fontSize?: number; lineHeight?: number; width?: number } | null
}

/** 与 BFF 一致的键区间（防御：越界值不应用，退回全局）。 */
const READER_STYLE_RANGES: Record<keyof SourceReaderStyle, [number, number]> = {
  fontSize: [12, 28],
  lineHeight: [1.4, 2.6],
  width: [480, 1600],
}

function inRange(value: unknown, range: [number, number]): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= range[0] && value <= range[1]
}

/**
 * 解析当前条目应应用的 per-source 阅读样式覆盖。
 *
 * - feedUrl 为空 / 列表为空 / 无匹配来源 → null；
 * - 匹配来源未配置 readerStyle → null；
 * - 移动端：width 键被忽略（即使服务端配置了）；
 * - 仅返回区间合法的键（非法值丢弃，退回全局）。
 */
export function resolveSourceReaderStyle(
  feedUrl: string | null | undefined,
  overrides: SourceOverrideLike[] | undefined | null,
  opts: { isMobile: boolean },
): SourceReaderStyle | null {
  if (!feedUrl || !Array.isArray(overrides)) return null
  const match = overrides.find((item) => item.feedUrl === feedUrl)
  const style = match?.readerStyle
  if (style === null || style === undefined || typeof style !== 'object') return null
  const result: SourceReaderStyle = {}
  if (inRange(style.fontSize, READER_STYLE_RANGES.fontSize)) result.fontSize = style.fontSize
  if (inRange(style.lineHeight, READER_STYLE_RANGES.lineHeight)) result.lineHeight = style.lineHeight
  // width 移动端忽略：视口钳制下覆盖宽度无意义。
  if (!opts.isMobile && inRange(style.width, READER_STYLE_RANGES.width)) result.width = style.width
  if (result.fontSize === undefined && result.lineHeight === undefined && result.width === undefined) {
    return null
  }
  return result
}

/** 覆盖值 → 正文容器内联 CSS 变量（消费端与全局管线同一组变量名；
 * 未覆盖的键不设置，继续继承根节点上的全局值）。 */
export function readerStyleCssVars(style: SourceReaderStyle | null): Record<string, string> {
  if (style === null) return {}
  const vars: Record<string, string> = {}
  if (style.fontSize !== undefined) vars['--lumi-reader-font-size'] = `${style.fontSize}px`
  if (style.lineHeight !== undefined) vars['--lumi-reader-line-height'] = String(style.lineHeight)
  if (style.width !== undefined) vars['--lumi-reader-content-width'] = `${style.width}px`
  return vars
}
